# E2E ML Задача: Предсказание цен NVIDIA

## 🎯 Описание задачи
Создать **минимальный** end-to-end ML проект для парсинга исторических данных акций NVIDIA (NVDA) и предсказания **цены закрытия на следующий день** с использованием линейной регрессии.

## 📁 Структура проекта
```
e2e_minimal/
├── main.py          # Основной ML пайплайн (100 строк)
├── requirements.txt # Зависимости
└── README.md       # Описание проекта
```

## 📋 Технические требования

### main.py
```python
def main():
    # 1. Парсинг NVDA данных (yfinance, 2 года)
    # 2. Feature Engineering (5 фич)
    # 3. Target = Close.shift(-1)
    # 4. Train/Test split (80/20)
    # 5. LinearRegression обучение
    # 6. MSE на тесте
    # 7. Предсказание "завтра"
    # 8. print("e2e_ok")

if __name__ == "__main__":
    main()
    print("e2e_ok")
```

### Обязательные фичи (Feature Engineering)
| Фича | Описание | Код |
|------|----------|-----|
| `Prev_Close` | Цена вчера | `Close.shift(1)` |
| `Returns` | Изменение % | `Close.pct_change()` |
| `MA5` | SMA 5 дней | `Close.rolling(5).mean()` |
| `MA20` | SMA 20 дней | `Close.rolling(20).mean()` |
| `RSI` | RSI(14) | Стандартная формула |

### requirements.txt
```
yfinance
pandas
numpy
scikit-learn
```

## ✅ Критерии приемки

| № | Критерий | Проверка |
|---|----------|----------|
| 1 | Компилируется | `python -m py_compile main.py` |
| 2 | Запускается | `pip install -r requirements.txt && python main.py` |
| 3 | Выводит MSE | `MSE на тесте: XXX.XX` |
| 4 | Предсказание | `Предсказанная цена NVDA: $XXX.XX` |
| 5 | Завершение | `e2e_ok` |

## 📊 Ожидаемый вывод
```
MSE на тесте: 12.45
Предсказанная цена NVDA на следующий день: $145.67
e2e_ok
```

## 🚀 Запуск
```bash
# Клонировать/создать проект
pip install -r requirements.txt
python main.py
```

## 📈 Типичность ML задачи
- **Парсинг**: yfinance API → DataFrame
- **Фичи**: Лаги, скользящие средние, RSI
- **Target**: `Next_Close = Close.shift(-1)`
- **Модель**: LinearRegression (базовая регрессия)
- **Метрика**: MSE
- **Прогноз**: Последний день → "завтра"

**Готовый пайплайн**: от сырых данных → обученная модель → предсказание цены за 100 строк кода.