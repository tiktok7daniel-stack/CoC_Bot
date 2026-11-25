#pragma once

#include <limits>

#include "AbilityEffect.h"
#include "Board.h"
#include "CardFactories.h"
#include "CombatEntity.h"
#include "OnHitEffect.h"

class FrostyFellaSnowman : public Entity {
    static constexpr int lifetime = 50;
    int initialHp;
    int ticksLeft = lifetime;
    int emptyTicks = 0;
    std::vector<int> frozen;

public:
    FrostyFellaSnowman(int id, const Vector2D& point, int health, int team)
        : Entity(id, point.x, point.y, health, team, 's'), initialHp(health) {
        name = "Snowman";
        cardId = -49;
    }

    void rememberTarget(int id) { frozen.push_back(id); }

    void update(Board& board) override {
        const bool anyFrozen = std::any_of(frozen.begin(), frozen.end(),
            [&board](int id) { return board.hasLivingEntity(id); });
        if (!anyFrozen && ++emptyTicks >= 20) {
            hp = 0;
            return;
        }
        const int previous = initialHp * ticksLeft / lifetime;
        --ticksLeft;
        hp -= previous - initialHp * ticksLeft / lifetime;
    }

    std::shared_ptr<Entity> snapshot() const override {
        return std::make_shared<FrostyFellaSnowman>(*this);
    }
};

class HeroIceWizardFrostyFellaEffect : public IAbilityEffect, public IOnHitEffect {
    static constexpr int slowTicks = 30;

    static void spawn(Board& board, CombatEntity& self, const CombatEntity& anchor) {
        self.frostyFellaArmed = false;
        Vector2D point = anchor.position;
        point.y += self.team == 0 ? 1.0f : -1.0f;
        point = board.clampToBoard(point, true);
        const float scale = CardFactories::teamLevelScale(self.team);
        auto snowman = std::make_shared<FrostyFellaSnowman>(
            board.allocateId(), point, std::max(1, static_cast<int>(std::lround(266 * scale))), self.team);
        board.addEntity(snowman);
        for (const auto& entity : board.getEntities()) {
            if (entity->team == self.team || !entity->isAlive() || !entity->isTargetable() ||
                point.distanceTo(entity->position) > 2.5f) continue;
            auto target = std::dynamic_pointer_cast<CombatEntity>(entity);
            if (!target) continue;
            const int damage = static_cast<int>(std::lround((target->isTower() ? 38 : 89) * scale));
            target->takeDamage(damage);
            board.statsEvents.notifyDamageDealt({self.id, self.team, self.cardId, target->id, target->cardId,
                target->team, damage, board.currentTick, target->isTower()});
            if (target->isAlive()) {
                target->applyFreeze(50, 0.0f, snowman->id);
                snowman->rememberTarget(target->id);
            }
        }
    }

public:
    void apply(Board& board, CombatEntity& self) const override {
        self.frostyFellaArmed = true;
        std::shared_ptr<CombatEntity> nearest;
        float distance = std::numeric_limits<float>::max();
        for (const auto& entity : board.getEntities()) {
            if (entity->team == self.team || !entity->isAlive() || !entity->isTargetable()) continue;
            auto target = std::dynamic_pointer_cast<CombatEntity>(entity);
            if (!target) continue;
            const auto& marks = target->iceWizardSlowUntil;
            const bool marked = std::any_of(marks.begin(), marks.end(), [&](const auto& mark) {
                return mark.first == self.id && mark.second > board.currentTick;
            });
            const float candidate = self.position.distanceTo(target->position);
            if (marked && candidate < distance) {
                distance = candidate;
                nearest = target;
            }
        }
        if (nearest) spawn(board, self, *nearest);
    }

    void onOwnerDeath(Board& board, CombatEntity& self) const override {
        if (self.frostyFellaArmed) board.pendingElixirGrant[self.team] += self.abilityElixirCost;
    }

    void apply(std::shared_ptr<CombatEntity> target) const override { target->applyFreeze(slowTicks, 0.65f); }

    void applyFrom(Board& board, int attackerId, const std::shared_ptr<CombatEntity>& target) const override {
        apply(target);
        if (!target->isAlive()) return;
        for (const auto& entity : board.getEntities()) {
            if (entity->id != attackerId || entity->team == target->team || !entity->isAlive()) continue;
            auto self = std::dynamic_pointer_cast<CombatEntity>(entity);
            if (!self) return;
            auto& marks = target->iceWizardSlowUntil;
            std::erase_if(marks, [&](const auto& mark) {
                return mark.first == attackerId || mark.second <= board.currentTick;
            });
            marks.emplace_back(attackerId, board.currentTick + slowTicks);
            if (self->frostyFellaArmed) spawn(board, *self, *target);
            return;
        }
    }
};
