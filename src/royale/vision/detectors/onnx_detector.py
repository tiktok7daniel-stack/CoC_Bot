import os, threading, time

import numpy as np
import onnxruntime as ort

# One model at a time on the graphics card: two DirectML runs from two threads at once took the whole bot down
# (5.35), the processor alone was too slow on a busy PC (925 ms a look, 5.38). Every model of the Clash Royale
# eyes (these and royale.strong_eyes) runs under this lock: one after the other on the card, ~10-80 ms each.
GPU_LOCK = threading.RLock()


def providers():
    av = ort.get_available_providers()
    return [p for p in ("TensorrtExecutionProvider", "CUDAExecutionProvider", "DmlExecutionProvider") if p in av] + \
        ["CPUExecutionProvider"]


class OnnxDetector:
    _SCALE = (np.arange(256, dtype=np.float32) / 255).astype(np.float16)
    def __init__(self, model_path):
        self.model_path = model_path

        try:                                   # TensorRT FP16 -> CUDA -> DirectML -> processor (6.6, trt_engine)
            import trt_engine
            self.sess = trt_engine.make_session(self.model_path, threads=max(2, (os.cpu_count() or 4) // 2))
        except Exception:
            so = ort.SessionOptions()
            so.intra_op_num_threads = max(2, (os.cpu_count() or 4) // 2)
            self.sess = ort.InferenceSession(self.model_path, sess_options=so, providers=["CPUExecutionProvider"])
        self.gpu = self.sess.get_providers()[0] != "CPUExecutionProvider"
        self._gpu_retry_at = 0.0
        self._threads = max(2, (os.cpu_count() or 4) // 2)
        self.output_name = self.sess.get_outputs()[0].name

        input_ = self.sess.get_inputs()[0]
        self.input_name = input_.name
        self.model_height, self.model_width = input_.shape[2:]

    def resize(self, x):
        ratio = x.height / x.width
        if ratio > self.model_height / self.model_width:
            height = self.model_height
            width = int(self.model_height / ratio)
        else:
            width = self.model_width
            height = int(self.model_width * ratio)

        x = x.resize((width, height))
        return x

    def pad(self, x):
        height, width = x.shape[:2]
        dx = self.model_width - width
        dy = self.model_height - height
        pad_right = dx // 2
        pad_left = dx - pad_right
        pad_bottom = dy // 2
        pad_top = dy - pad_bottom
        padding = [pad_left, pad_right, pad_top, pad_bottom]
        x = np.pad(
            x,
            ((pad_top, pad_bottom), (pad_left, pad_right), (0, 0)),
            mode="constant",
            constant_values=114,
        )
        return x, padding

    def resize_pad_transpose_and_scale(self, image):
        image = self.resize(image)
        image = np.asarray(image)
        image, padding = self.pad(image)
        image = self._SCALE[image.transpose(2, 0, 1)]
        return image, padding

    def fix_bboxes(self, x, width, height, padding):
        x[:, [0, 2]] -= padding[0]
        x[:, [1, 3]] -= padding[2]
        x[..., [0, 2]] *= width / (self.model_width - padding[0] - padding[1])
        x[..., [1, 3]] *= height / (
            self.model_height - padding[2] - padding[3]
        )
        return x

    def _rebuild_gpu(self):
        """Try creating a fresh GPU session once; returns True if a non-CPU provider is active."""
        self._gpu_retry_at = time.monotonic() + 60.0
        try:
            import trt_engine
            ns = trt_engine.make_session(self.model_path, threads=self._threads)
            if ns.get_providers()[0] != "CPUExecutionProvider":
                self.sess = ns
                self.gpu = True
                self._gpu_retry_at = 0.0
                return True
        except Exception:
            pass
        return False

    def _run_raw(self, x):
        if self.gpu and getattr(self.sess, "kind", "dml") == "dml":
            with GPU_LOCK:
                return self.sess.run([self.output_name], {self.input_name: x})[0]
        return self.sess.run([self.output_name], {self.input_name: x})[0]

    def _infer(self, x):
        if not self.gpu and self._gpu_retry_at and time.monotonic() >= self._gpu_retry_at:
            self._rebuild_gpu()
        try:
            return self._run_raw(x)
        except Exception:
            if self.gpu and self._rebuild_gpu():
                try:
                    return self._run_raw(x)
                except Exception:
                    pass
            so = ort.SessionOptions()
            so.intra_op_num_threads = self._threads
            self.sess = ort.InferenceSession(self.model_path, sess_options=so, providers=["CPUExecutionProvider"])
            self.gpu = False
            self._gpu_retry_at = time.monotonic() + 60.0
            return self.sess.run([self.output_name], {self.input_name: x})[0]

    def run(self, image):
        raise NotImplementedError
