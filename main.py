import pandas as pd
import telebot
from telebot import types
import io
import requests
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Настройки бота
TOKEN = 'TG_BOT_TOKEN'
bot = telebot.TeleBot(TOKEN)


# Функция для загрузки и обработки данных
def load_schedule_from_github(url):
    try:
        logger.info(f"Начинаем загрузку файла по URL: {url}")
        response = requests.get(url)
        response.raise_for_status()

        # Определяем движок для чтения Excel
        engine = 'xlrd' if url.endswith('.xls') else 'openpyxl'
        logger.info(f"Используем движок: {engine}")

        xls = pd.ExcelFile(io.BytesIO(response.content), engine=engine)
        schedule = {}

        for sheet_name in xls.sheet_names:
            try:
                logger.info(f"Обрабатываем лист: {sheet_name}")
                df = pd.read_excel(xls, sheet_name=sheet_name, header=None)

                # Поиск строки с названиями групп
                groups_row = None
                for i in range(min(15, len(df))):  # Проверяем первые 15 строк
                    row_values = [str(cell) for cell in df.iloc[i].values if pd.notna(cell)]
                    # Проверяем наличие типичных префиксов групп
                    if any(any(p in val.upper() for p in ['ИС', 'МР', 'ПК', 'ТИК', 'ПО', 'ТГ', 'ТД']) for val in
                           row_values):
                        groups_row = i
                        break

                if groups_row is None:
                    logger.warning(f"Не найдена строка с группами в листе {sheet_name}")
                    continue

                # Извлекаем названия групп
                groups = []
                for cell in df.iloc[groups_row].values:
                    if pd.notna(cell):
                        cell_str = str(cell).strip()
                        if any(p in cell_str.upper() for p in ['ИС', 'МР', 'ПК', 'ТИК', 'ПО', 'ТГ', 'ТД']):
                            groups.append(cell_str)

                if not groups:
                    logger.warning(f"Не найдено групп в листе {sheet_name}")
                    continue

                logger.info(f"Найдены группы: {groups}")

                # Обработка расписания
                current_day = None
                day_schedule = {group: {} for group in groups}

                for idx, row in df.iloc[groups_row + 1:].iterrows():
                    # Проверяем начало нового дня
                    if pd.notna(row[0]):
                        day_str = str(row[0])
                        if 'Понед' in day_str:
                            current_day = 'Понедельник'
                        elif 'Вторн' in day_str:
                            current_day = 'Вторник'
                        elif 'Среда' in day_str:
                            current_day = 'Среда'
                        elif 'Четв' in day_str:
                            current_day = 'Четверг'
                        elif 'Пятн' in day_str:
                            current_day = 'Пятница'
                        else:
                            continue

                    if current_day and pd.notna(row[1]):  # Если есть номер пары
                        try:
                            pair_num = int(row[1])
                            for i, group in enumerate(groups):
                                col_subject = 2 + i * 2
                                col_teacher = col_subject + 1

                                if col_teacher >= len(row):  # Проверяем границы
                                    continue

                                subject = str(row[col_subject]).strip() if pd.notna(row[col_subject]) else ''
                                teacher = str(row[col_teacher]).strip() if pd.notna(row[col_teacher]) else ''

                                if subject or teacher:
                                    if current_day not in day_schedule[group]:
                                        day_schedule[group][current_day] = {}
                                    day_schedule[group][current_day][pair_num] = f"{subject} ({teacher})"
                        except (ValueError, IndexError) as e:
                            logger.error(f"Ошибка обработки строки {idx}: {e}")
                            continue

                # Добавляем расписание для этого листа
                for group in groups:
                    if group not in schedule:
                        schedule[group] = {}
                    schedule[group].update(day_schedule[group])

            except Exception as e:
                logger.error(f"Ошибка при обработке листа {sheet_name}: {str(e)}")
                continue

        logger.info("Загрузка расписания завершена успешно")
        return schedule

    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при загрузке файла: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Общая ошибка: {str(e)}")
        return None


# Загрузка расписания (используем raw-URL)
SCHEDULE_URL = 'https://github.com/lL1x3/schedule_1x3_hub/raw/main/12 ц 31.03-4.04 2 КУРС БАССЕЙН.xls'
schedule_data = load_schedule_from_github(SCHEDULE_URL)


# Обработчики команд бота
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    help_text = (
        "Привет! Я бот для расписания.\n\n"
        "Доступные команды:\n"
        "/start - начать работу\n"
        "/help - показать это сообщение\n"
        "/groups - показать список групп\n\n"
        "Просто введите название группы (например, ИС24-02) для получения расписания."
    )
    bot.reply_to(message, help_text)


@bot.message_handler(commands=['groups'])
def list_groups(message):
    if schedule_data is None:
        bot.reply_to(message, "Расписание временно недоступно. Попробуйте позже.")
        return

    groups = sorted(schedule_data.keys())
    if not groups:
        bot.reply_to(message, "Группы не найдены в расписании.")
        return

    response = "Доступные группы:\n\n" + "\n".join(groups)
    bot.reply_to(message, response)


@bot.message_handler(func=lambda message: True)
def send_schedule(message):
    input_group = message.text.strip().upper()  # Приводим к верхнему регистру

    if schedule_data is None:
        bot.reply_to(message, "Извините, расписание временно недоступно. Попробуйте позже.")
        return

    # Ищем группу с учетом возможных различий в написании
    found_group = None
    for group in schedule_data.keys():
        # Удаляем возможные пробелы и приводим к верхнему регистру
        cleaned_group = group.replace(" ", "").upper()
        cleaned_input = input_group.replace(" ", "").upper()

        if cleaned_group == cleaned_input:
            found_group = group
            break

    if not found_group:
        # Попробуем найти похожие группы
        similar_groups = [
            g for g in schedule_data.keys()
            if input_group.replace(" ", "").upper() in g.replace(" ", "").upper()
        ]

        if similar_groups:
            response = f"Группа '{input_group}' не найдена. Возможно, вы имели в виду:\n\n"
            response += "\n".join(similar_groups)
            response += "\n\nПопробуйте ввести название еще раз или введите /groups для полного списка."
        else:
            response = "Группа не найдена. Пожалуйста, проверьте название и попробуйте еще раз.\n"
            response += "Или введите /groups для просмотра списка доступных групп."

        bot.reply_to(message, response)
        return

    # Формируем ответ с расписанием
    response = f"📅 Расписание для группы {found_group}:\n\n"

    days_order = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница']
    for day in days_order:
        if day in schedule_data[found_group]:
            response += f"📌 {day}:\n"
            for pair_num in sorted(schedule_data[found_group][day].keys()):
                response += f"{pair_num}. {schedule_data[found_group][day][pair_num]}\n"
            response += "\n"

    if len(response.strip()) == len(f"📅 Расписание для группы {found_group}:\n\n"):
        response = f"Для группы {found_group} не найдено расписания."

    if len(response) > 4000:
        for x in range(0, len(response), 4000):
            bot.send_message(message.chat.id, response[x:x + 4000])
    else:
        bot.send_message(message.chat.id, response)


# Запуск бота
if __name__ == '__main__':
    logger.info("Бот запущен...")
    try:
        bot.polling(none_stop=True, interval=2)
    except Exception as e:
        logger.error(f"Ошибка в работе бота: {str(e)}")