.PHONY: help install run dev clean test

help:
	@echo "Доступные команды:"
	@echo "  install - Установка зависимостей"
	@echo "  run     - Запуск приложения"
	@echo "  dev     - Запуск в режиме разработки с автоперезагрузкой"
	@echo "  clean   - Очистка временных файлов"

install:
	pip install -r requirements.txt

run:
	python -m uvicorn app.main:app --host 0.0.0.0 --port 8080

dev:
	python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache
