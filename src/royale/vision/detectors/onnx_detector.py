import os, threading

import numpy as np
import onnxruntime as ort

# One model at a time on the graphics card: two DirectML runs from two threads at once took the whole bot down
# (5.35), the processor alone was too slow on a busy PC (925 ms a look, 5.38). Every model of the Clash Royale
# eyes (these and royale.strong_eyes) runs under this lock: one after the other on the card, ~10-80 ms each.
GPU_LOCK = threading.RLock()


def providers():
    av = ort.get_available_providers()
    return [p for p in ("CUDAExecutionProvider", "DmlExecutionProvider") if p in av] + ["CPUExecutionProvider"]


class OnnxDetector:
    def __init__(self, model_path):
        self.model_path = model_path

        so = ort.SessionOptions()
        so.intra_op_num_threads = max(2, (os.cpu_count() or 4) // 2)
        try:
            self.sess = ort.InferenceSession(self.model_path, sess_options=so, providers=providers())
        except Exception:
            self.sess = ort.InferenceSession(self.model_path, sess_options=so, providers=["CPUExecutionProvider"])
        self.gpu = self.sess.get_providers()[0] != "CPUExecutionProvider"
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
        image = np.array(image, dtype=np.float16)
        image, padding = self.pad(image)
        image = image.transpose(2, 0, 1)
        image /= 255
        return image, padding

    def fix_bboxes(self, x, width, height, padding):
        x[:, [0, 2]] -= padding[0]
        x[:, [1, 3]] -= padding[2]
        x[..., [0, 2]] *= width / (self.model_width - padding[0] - padding[1])
        x[..., [1, 3]] *= height / (
            self.model_height - padding[2] - padding[3]
        )
        return x

    def _infer(self, x):
        if not self.gpu:
            return self.sess.run([self.output_name], {self.input_name: x})[0]
        try:
            with GPU_LOCK:
                return self.sess.run([self.output_name], {self.input_name: x})[0]
        except Exception:                        # the card said no: this model goes on on the processor
            so = ort.SessionOptions()
            so.intra_op_num_threads = max(2, (os.cpu_count() or 4) // 2)
            self.sess = ort.InferenceSession(self.model_path, sess_options=so, providers=["CPUExecutionProvider"])
            self.gpu = False
            return self.sess.run([self.output_name], {self.input_name: x})[0]

    def run(self, image):
        raise NotImplementedError
