# Dungeonfall

Пиксельный roguelike-шутер на Python и Pygame CE. Искатель и Дозорная спускаются через 15 процедурных этажей и сражаются с тремя хранителями подземелья. Игра рисуется на сетке 640×360, которая масштабируется без сглаживания. **F11** переключает полноэкранный режим.

## Запуск

На Windows распакуй архив и запусти **Play-Dungeonfall.cmd**. Для него нужен Python 3.14. Скрипт создаст виртуальное окружение, установит Pygame CE и откроет игру. При первой установке зависимости нужен интернет.

На Ubuntu открой терминал в папке с `main.py` и `requirements.txt` и выполни:

```bash
sudo apt update
sudo apt install -y python3-full
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
```

При повторных запусках достаточно `.venv/bin/python main.py`. Если предпочитаешь установленный отдельно Python 3.14, подставь `python3.14` вместо `python3` при создании окружения. Сборка проверена с Python 3.14.7 и Pygame CE 2.5.8.
