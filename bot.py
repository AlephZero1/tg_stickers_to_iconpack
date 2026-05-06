import os
import shutil
import logging
import subprocess
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
from PIL import Image

import uuid
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = str(os.getenv("BOT_TOKEN")) # TG токен
RH_PATH = str(os.getenv("RH_PATH"))  # Путь к ResourceHacker.exe
TEMPLATE_DLL_PATH = str(os.getenv("TEMPLATE_DLL_PATH"))  # Путь к ddores.dll

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def convert_webp_to_png(webp_path: str, png_path: str) -> bool:
    try:
        with Image.open(webp_path) as img:
            img.save(png_path, "PNG")
        return True
    except Exception as e:
        logging.error(f"Ошибка конвертации WEBP->PNG: {e}")
        return False

def convert_png_to_ico(png_path: str, ico_path: str) -> bool:
    try:
        with Image.open(png_path) as img:
            sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
            img.save(ico_path, format='ICO', sizes=sizes)
        return True
    except Exception as e:
        logging.error(f"Ошибка конвертации PNG->ICO: {e}")
        return False

def create_dll_from_icons(icons_dir: str, dll_path: str, template_dll: str, rh_path: str) -> bool:
    try:
        shutil.copy(template_dll, dll_path)
        logging.info(f"Шаблон скопирован: {dll_path}")
    except Exception as e:
        logging.error(f"Ошибка копирования шаблона: {e}")
        return False

    icons = [f for f in os.listdir(icons_dir) if f.endswith('.ico')]
    icons.sort(key=lambda x: int(x.split('_')[1].split('.')[0]))
    if not icons:
        logging.error("Нет ICO-файлов для добавления.")
        return False

    for i, ico_file in enumerate(icons):
        icon_index = i + 1  # Индексация с 1
        icon_path = os.path.join(icons_dir, ico_file)
        cmd = ['xvfb-run','-a','wine',
            rh_path,
            '-open', dll_path,
            '-save', dll_path,
            '-action', 'addoverwrite',  # Ключевая команда для замены
            '-res', icon_path,
            '-mask', f'ICON,{icon_index},'
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                logging.error(f"Resource Hacker ошибка для {ico_file}: {result.stderr}")
                return False
            logging.info(f"Иконка {ico_file} добавлена как ресурс #{icon_index}")
        except Exception as e:
            logging.error(f"Ошибка запуска Resource Hacker: {e}")
            return False

    return True

def cleanup_directory(directory: str):
    if os.path.exists(directory):
        shutil.rmtree(directory)
        logging.info(f"Временная папка {directory} удалена.")


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я бот для конвертации Telegram-стикерпаков в иконки Windows.\n\n"
        "Просто отправь мне **ссылку** на стикерпак (например, `AnimatedStickersPack`), и я:\n"
        "1. Скачаю стикеры\n"
        "2. Конвертирую их в ICO\n"
        "3. Упакую в DLL-файл`\n"
        "4. Пришлю готовую библиотеку.\n\n"
        "⚠️ Размер итогового файла не должен превышать 50 МБ."
    )

@dp.message()
async def handle_sticker_pack(message: types.Message):
    to_parse = message.text.strip()
    pack_name = to_parse.strip().rstrip('/').split('/')[-1]
    user_id = message.from_user.id
    temp_dir = f"temp_{user_id}_{uuid.uuid4().hex}" # Уникальная папка

    status_msg = await message.answer(f"🔍 Получаю стикерпак `{pack_name}`...")

    # 1. Поиск стикерпака
    try:
        sticker_set = await bot.get_sticker_set(pack_name)
    except Exception:
        await status_msg.edit_text(f"❌ Стикерпак `{pack_name}` не найден. Проверьте название.")
        return

    if not sticker_set.stickers:
        await status_msg.edit_text("❌ В этом стикерпаке нет стикеров.")
        return

    os.makedirs(temp_dir, exist_ok=True)
    await status_msg.edit_text(f"📦 Найдено {len(sticker_set.stickers)} стикеров. Обрабатываю...")

    # 2. Обработка стикеров
    for i, sticker in enumerate(sticker_set.stickers):
        if i % 5 == 0: # Обновляем инфу каждые 5 стикеров
            await status_msg.edit_text(f"🔄 Обработка: {i}/{len(sticker_set.stickers)}")
        file_info = await bot.get_file(sticker.file_id)
        downloaded_file = await bot.download_file(str(file_info.file_path))
        webp_path = os.path.join(temp_dir, f"sticker_{i}.webp")
        with open(webp_path, 'wb') as f:
            f.write(downloaded_file.getvalue())
        # Конвертируем в PNG
        png_path = os.path.join(temp_dir, f"sticker_{i}.png")
        if not convert_webp_to_png(webp_path, png_path):
            await status_msg.edit_text(f"❌ Ошибка конвертации стикера {i+1}.")
            cleanup_directory(temp_dir)
            return
        # Конвертируем в ICO
        ico_path = os.path.join(temp_dir, f"sticker_{i}.ico")
        if not convert_png_to_ico(png_path, ico_path):
            await status_msg.edit_text(f"❌ Ошибка конвертации стикера {i+1} в ICO.")
            cleanup_directory(temp_dir)
            return

        # Удаляем временные файлы
        os.remove(webp_path)
        os.remove(png_path)

    await status_msg.edit_text(f"✅ Сконвертировано {len(sticker_set.stickers)} иконок. Создаю DLL...")

    # 3. Создаём DLL
    dll_name = f"{pack_name}.dll"
    dll_path = os.path.join(temp_dir, dll_name)

    if not os.path.exists(TEMPLATE_DLL_PATH):
        await status_msg.edit_text("❌ Ошибка: системный шаблон ddores.dll не найден.")
        cleanup_directory(temp_dir)
        return

    if not create_dll_from_icons(temp_dir, dll_path, TEMPLATE_DLL_PATH, RH_PATH):
        await status_msg.edit_text("❌ Ошибка при создании DLL.")
        cleanup_directory(temp_dir)
        return

    await status_msg.edit_text("📤 Отправляю DLL...")

    # 4. Отправляем результат
    try:
        document = FSInputFile(dll_path, filename=dll_name)
        await message.answer_document(
            document=document,
            caption=f"✅ Готово! DLL для `{pack_name}` содержит {len(sticker_set.stickers)} иконок.\n\n"
                    "**Как использовать:**\n"
                    "1. Скопируйте файл в удобное место.\n"
                    "2. В свойствах папки → 'Настройка' → 'Сменить иконку' → 'Обзор'.\n"
                    "3. Выберите этот DLL и укажите номер иконки (1, 2, 3...)."
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка отправки: {e}. Возможно, файл слишком большой.")
        logging.error(f"Ошибка отправки: {e}")

    # 5. Очистка
    cleanup_directory(temp_dir)
    await status_msg.delete()

async def main():
    logging.info("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())