Исследование кварталов Магнитогорска
====================================

.. logo-start

.. logo-end

.. readme-start

Практика № 2 по исследованию городской структуры Магнитогорска с помощью
``BlocksNet 1.0.0a9``. Репозиторий содержит выполненный ноутбук, итоговые
геоданные и автономный интерактивный HTML-дашборд.

Готовые материалы
-----------------

* ``examples/magnitogorsk_pipeline.ipynb`` — последовательный расчёт кварталов
  и показателей с сохранёнными результатами выполнения;
* ``dashboard.html`` — готовый автономный дашборд, открывается без сервера;
* ``examples/build_magnitogorsk_dashboard.py`` — повторная сборка HTML только
  из сохранённых результатов, без загрузок и повторных расчётов;
* ``examples/magnitogorsk_audit.md`` — сверка показателей ноутбука и дашборда;
* ``examples/data_magnitogorsk/results_blocks.geojson`` — итоговый слой кварталов;
* ``examples/data_magnitogorsk/results_table.csv`` и ``summary.csv`` — итоговая
  таблица и общегородская сводка.

Быстрый просмотр
----------------

Скачайте репозиторий и откройте ``dashboard.html`` в браузере. Интернет для
просмотра не нужен: карта, диаграммы и таблицы встроены в один файл.

Установка на Windows
--------------------

Требуется Python 3.10 или новее. Проект проверялся в Windows 11 с Python 3.12.

.. code-block:: powershell

   git clone https://github.com/cesha2003-web/urban-ai-practice.git
   cd urban-ai-practice
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements-magnitogorsk.txt

Сборка HTML из сохранённых данных
---------------------------------

.. code-block:: powershell

   .\.venv\Scripts\python.exe .\examples\build_magnitogorsk_dashboard.py

Команда читает готовые GeoJSON/CSV/JSON, создаёт ``dashboard.html`` в корне
проекта и не обращается к сети. Полный пересчёт города для сборки не требуется.

Работа с ноутбуком
------------------

Откройте ``examples/magnitogorsk_pipeline.ipynb`` в VS Code и выберите
``.venv\Scripts\python.exe``. После перезапуска ядра сначала выполните ячейку
``5.0. ВОССТАНОВЛЕНИЕ СОСТОЯНИЯ``. Подробный безопасный порядок повторного
использования сохранённых результатов приведён в ``examples/magnitogorsk_audit.md``.

Ограничения набора данных
-------------------------

Региональный ``ural-fed-district-latest.osm.pbf``, граф, полная матрица времени,
кэши и резервные копии не публикуются из-за размера. Они нужны только для полного
пересчёта исходных этапов и не требуются для готового дашборда. Опубликованные
результаты основаны на реальных геометриях OpenStreetMap; фиктивные объекты не
использовались.

Лицензия
--------

Код проекта распространяется на условиях BSD-3-Clause, см. ``LICENSE``.

.. readme-end
