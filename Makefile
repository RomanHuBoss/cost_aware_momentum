.PHONY: setup configure db-init migrate doctor up api worker trainer test lint backup restore-check report

PYTHON ?= python

setup:
	$(PYTHON) manage.py setup

configure:
	$(PYTHON) manage.py configure

db-init:
	$(PYTHON) manage.py db-init

migrate:
	$(PYTHON) manage.py migrate

doctor:
	$(PYTHON) manage.py doctor

up:
	$(PYTHON) manage.py run

api:
	$(PYTHON) manage.py api

worker:
	$(PYTHON) manage.py worker

trainer:
	$(PYTHON) manage.py trainer

test:
	$(PYTHON) manage.py test

lint:
	$(PYTHON) manage.py lint

backup:
	$(PYTHON) manage.py backup

restore-check:
	$(PYTHON) manage.py restore-check

report:
	$(PYTHON) manage.py report --output reports/daily_report.json
