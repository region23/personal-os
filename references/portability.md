# Подключение и переносимость

Пути сверены с официальной документацией 2026-10-19. Живой прогон 2026-10-19 — настройка, первая заметка, новый чат, запись, обзор недели — пройден в Claude Code 2.1 и Codex CLI 0.162. OpenCode и DeepSeek Harness сверены только по документации.

## Формат

Пакет — папка с `SKILL.md` в открытом [формате Agent Skills](https://agentskills.io/specification). Особых разрешений, модели, MCP-сервера или поставщика API не требует. Копируй папку `personal-os` целиком: без `assets/`, `references/` и `scripts/` скилл не работает. Держи одну копию, чтобы не было дублей с одинаковым именем.

## Где лежит скилл установки

Пути — от папки, в которой запускается агент, или от домашнего каталога (`~`) для установки только себе. Глобальную установку выбирает владелец.

| Клиент | Папка скилла | Правила базы читает из |
|---|---|---|
| Codex | `.agents/skills/personal-os/`, `~/.agents/skills/` | `AGENTS.md` |
| Claude Code | `.claude/skills/personal-os/`, `~/.claude/skills/` | `CLAUDE.md`; `AGENTS.md` — только если `CLAUDE.md` нет ни в папке, ни выше |
| OpenCode | `.agents/skills/`, `.opencode/skills/`, `.claude/skills/` | `AGENTS.md`, запасной — `CLAUDE.md` |
| DeepSeek Harness, preview | `.agents/skills/`, `.dsh/skills/` | `AGENTS.md` и `CLAUDE.md`, без раскрытия `@`-импортов |

Документация: [Codex: скиллы](https://learn.chatgpt.com/docs/build-skills), [Codex: AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md), [Claude Code: скиллы](https://code.claude.com/docs/en/skills), [Claude Code: память](https://code.claude.com/docs/en/memory), [OpenCode: скиллы](https://opencode.ai/docs/skills), [OpenCode: правила](https://opencode.ai/docs/rules/), [DeepSeek Harness: скиллы](https://deepseek-harness.github.io/deepseek-harness/en/reference/subsystems/skills), [DeepSeek Harness: инструкции](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/context/agent-instructions/README.md).

Без установки тоже работает: открой папку пакета агентом и попроси «Прочитай SKILL.md и создай мою Personal OS в папке ../my-personal-os».

## Созданная база

Канонические правила — самодостаточный `AGENTS.md`. Скиллы базы лежат в `.agents/skills/` — их находят Codex, OpenCode и DeepSeek Harness. Остальные файлы агент открывает по явным ссылкам из `AGENTS.md` и `README.md`, без особенностей одного клиента.

**Codex.** Открывай папку базы как рабочую: Codex собирает `AGENTS.md` от корня проекта до текущей папки, `AGENTS.override.md` имеет приоритет.

**Claude Code.** Не читает ничего из `.agents/` и пропускает `AGENTS.md`, если выше по дереву есть любой `CLAUDE.md`. Поэтому при настройке под Claude Code создай в корне базы адаптер:

1. `CLAUDE.md` из одной строки — импорт подтягивает правила, а повторно `AGENTS.md` не загружается:

   ```text
   @AGENTS.md
   ```

   Если `CLAUDE.md` уже есть — сохрани его и допиши строку, не перезаписывая.
2. Для каждого скилла базы — указатель `.claude/skills/<имя>/SKILL.md` с тем же `name` и `description`, что в `.agents/skills/<имя>/SKILL.md`, и телом из одной строки:

   ```text
   Прочитай и выполни `.agents/skills/<имя>/SKILL.md`.
   ```

Claude Code спрашивает разрешение на запись в `.claude/` — это нормально, разреши. Если указатели не созданы, база всё равно работает: `AGENTS.md` ведёт к скиллам по прямым путям, просто без вызова через `/inbox`.

OpenCode читает обе папки скиллов; указатели ведут на тот же файл, поэтому поведение не расходится.

**Другой клиент.** Используй его документированный способ подключать инструкции или стартовую фразу из `README.md` базы. При доступе только к тексту файлы можно передавать вручную, но и сохранять изменения придётся вручную.

## Что переносится

Переносятся файлы: контекст, история, правила, скиллы базы. Отдельно настраиваются: модель и её качество, права на файлы, учётные записи, фоновые задания, внешние сервисы. Для работы с базой достаточно читать и писать UTF-8 файлы; Python и Git необязательны.

После переезда проверь три вещи: агент называет текущий фокус, находит последнюю запись и сохраняет новую заметку так, что её можно найти повторно. Это и есть проверка совместимости в вашей среде.
