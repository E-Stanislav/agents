# Мультиагентный генератор проектов

Система на базе ИИ, которая по требованиям в Markdown создаёт полноценные проекты с помощью команды специализированных LLM-агентов, оркестрируемых LangGraph.

**Где указать Markdown с заданием**

- **Веб-интерфейс** — основной способ: после запуска откройте приложение в браузере, перетащите `.md` в зону загрузки *или* вставьте текст требований в поле и нажмите «Generate Project». Отдельный конфиг для текста задания не нужен.
- **HTTP API** — передайте содержимое в теле запроса (`md_content`) или загрузите файл через `POST /api/tasks/upload` (см. раздел «API» ниже).
- **Файл на диске** — можно положить готовый `.md` в каталог `tasks/` на машине с контейнером и использовать его как эталон/шаблон; для старта генерации всё равно нужен веб или API (система читает текст задачи из запроса, а не «автоматом» из папки при старте).

Итого: **Markdown не прописывается в `llm_config.yaml` и не в `.env`** — это содержимое задачи, которое вы даёте через UI или API.

## Архитектура

В графе состояний LangGraph задействованы 8 специализированных агентов:

| Агент | Роль | LLM по умолчанию |
|-------|------|------------------|
| **Orchestrator** | Управление потоком графа, маршрутизация | GPT-4o-mini |
| **Analyst** | Разбор требований, уточняющие вопросы | Claude Sonnet |
| **Architect** | Стек, структура файлов, граф зависимостей | Claude Sonnet |
| **Coder** | Генерация кода (параллельный fan-out по графу зависимостей) | Claude Sonnet |
| **Reviewer** | Оценка качества, паттерн Actor-Critic (другая модель) | GPT-4o |
| **Tester** | Линтеры и тесты в Docker-песочнице | GPT-4o |
| **Knowledge Base** | RAG по шаблонам и документации | Embeddings |
| **Delivery** | Сборка проекта, README, Dockerfile, инициализация Git | Claude Sonnet |

Назначение моделей для каждого агента настраивается в `llm_config.yaml` — поддерживаются любые API, совместимые с OpenAI (z.ai, MiniMax, Together, vLLM, Ollama и т.д.).

## Быстрый старт

```bash
# 1. Клонирование и настройка
cp .env.example .env
# Отредактируйте .env и укажите API-ключи

# 2. Запуск всех сервисов
docker compose up -d

# 3. Откройте веб-интерфейс (порт задаётся в .env: APP_PORT, по умолчанию 8000)
open http://localhost:8000
```

## Конфигурация

### Провайдеры LLM (`llm_config.yaml`)

Каждый агент может использовать своего провайдера и свой `base_url`:

```yaml
providers:
  openai:
    type: openai
    base_url: "https://api.openai.com/v1"
    api_key: "${OPENAI_API_KEY}"

  z_ai:
    type: openai_compatible
    base_url: "https://api.z.ai/v1"
    api_key: "${Z_AI_API_KEY}"

agents:
  coder:
    provider: z_ai
    model: "claude-sonnet-4-20250514"
    temperature: 0.1
    max_tokens: 16384
```

Типы провайдеров: `openai`, `anthropic`, `openai_compatible` (любой API, совместимый с OpenAI).

### Переменные окружения (`.env`)

API-ключи, URL баз данных и настройки сервисов. Полный список — в `.env.example`.

## Использование

### Веб-интерфейс

1. Откройте в браузере `http://localhost:<APP_PORT>` (значение задаётся в `.env` как `APP_PORT`, по умолчанию `8000`)
2. Загрузите файл `.md` или вставьте требования вручную
3. Ответьте на уточняющие вопросы (если есть)
4. Просмотрите и одобрите план архитектуры
5. Следите за ходом генерации кода в реальном времени
6. Скачайте готовый проект

### API

```bash
# Создать задачу
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"md_content": "# My Project\n\nBuild a REST API..."}'

# Загрузить MD-файл
curl -X POST http://localhost:8000/api/tasks/upload \
  -F "file=@requirements.md"

# Статус задачи
curl http://localhost:8000/api/tasks/{task_id}

# Скачать результат
curl -O http://localhost:8000/api/tasks/{task_id}/download
```

### WebSocket

Подключение к `ws://localhost:8000/ws/{task_id}` для интерактива в реальном времени с поддержкой interrupt/resume.

## Сервисы

| Сервис | Порт | Описание |
|--------|------|----------|
| App | 8000 | FastAPI + агенты LangGraph |
| PostgreSQL | 5432 | Checkpointing состояния и история |
| Redis | 6379 | Очередь задач |
| ChromaDB | 8100 | Векторное хранилище RAG |
| Langfuse | 3001 | Дашборд наблюдаемости LLM |
| Docker DinD | — | Изолированная песочница для выполнения кода |

## Структура проекта

```
├── docker-compose.yml       # 7 сервисов
├── Dockerfile               # Образ приложения
├── llm_config.yaml          # Конфигурация провайдеров LLM
├── .env.example             # Шаблон переменных окружения
├── requirements.txt         # Зависимости Python
├── src/
│   ├── main.py              # Точка входа FastAPI
│   ├── config.py            # Настройки приложения
│   ├── llm/                 # Реестр и фабрика LLM
│   ├── agents/              # Агенты LangGraph
│   ├── models/              # Pydantic-модели состояния
│   ├── sandbox/             # Управление Docker-песочницей
│   ├── knowledge_base/      # RAG на ChromaDB
│   ├── observability/       # Трейсинг Langfuse
│   ├── security/            # Rate limiting, budget guard
│   ├── api/                 # REST + WebSocket
│   ├── prompts/             # Промпты агентов (MD)
│   └── web/                 # Веб-интерфейс
├── templates/               # Шаблоны проектов для RAG
├── tasks/                   # Входные MD-файлы
└── output/                  # Сгенерированные проекты
```

## Основные возможности

- **Несколько провайдеров LLM**: для каждого агента — свой API, совместимый с OpenAI
- **Human-in-the-Loop**: `interrupt()` для уточняющих вопросов и утверждения архитектуры
- **Параллельная генерация кода**: fan-out/fan-in по графу зависимостей файлов
- **Self-Reflection**: паттерн Actor-Critic с разными моделями для Coder и Reviewer
- **RAG Knowledge Base**: шаблоны и документация повышают качество кода
- **Docker Sandbox**: изолированное выполнение кода с сетевым firewall
- **Observability**: трейсинг Langfuse для каждого вызова LLM
- **Budget Guard**: автоматическая остановка при достижении лимита стоимости

## Лицензия

MIT
