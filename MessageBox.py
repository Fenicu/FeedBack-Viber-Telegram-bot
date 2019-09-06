import telebot
from viberbot import Api
from viberbot.api.bot_configuration import BotConfiguration
from viberbot.api.messages.text_message import TextMessage
from viberbot.api.messages.keyboard_message import KeyboardMessage
from viberbot.api.viber_requests import ViberMessageRequest
from viberbot.api.messages import PictureMessage
from loguru import logger as logging
from re import sub
from pymongo import MongoClient
from telebot import types
import config as cfg

import requests
import httplib2

client = MongoClient()
db = client.FeedBot
db_users = db.users
db_settings = db.settings

def Message(t_bot, v_bot, message, user):
    settings = db_settings.find_one()
    if user['messenger'] == "viber": # Пользователь написал из вайбера
        if user['operator']['active session'] is None: # Сообщение поступает в чат операторов
            link = f"https://t.me/{t_bot.get_me().username}?start={user['system id']}"
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton(text="Ответить пользователю", url=link))
            #logging.info(message)
            if isinstance(message.message, PictureMessage):
                t_bot.send_photo(settings["main_id"], message.message.media, caption=f"{user['name']}, ({user['messenger']}) прислал изображение", reply_markup=keyboard)
                return True
            out = f"{user['name']}, ({user['messenger']}) прислал сообщение:\n{message.message.text}"
            t_bot.send_message(settings["main_id"], out, reply_markup=keyboard)
            return True
        else: # Диалог
            tolker = db_users.find_one({"system id": user['operator']['active session']})
            if isinstance(message.message, PictureMessage):
                t_bot.send_photo(tolker['_id'], message.message.media, caption=f"{user['name']}, ({user['messenger']}) прислал изображение")
                return True
            out = f"{user['name']}, ({user['messenger']}) прислал сообщение:\n{message.message.text}"
            t_bot.send_message(tolker["_id"], out)
            return True
    elif user['messenger'] == "telegram": # Пользователь написал из телеги
        if user['operator']['active session'] is None: # Сообщение поступает в чат операторов
            link = f"https://t.me/{t_bot.get_me().username}?start={user['system id']}"
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton(text="Ответить пользователю", url=link))
            if message.content_type == 'photo':
                t_bot.send_photo(settings["main_id"], message.photo[-1].file_id, caption=f"{user['name']}, ({user['messenger']}) прислал изображение", reply_markup=keyboard)
                return True
            out = f"{user['name']} ({user['messenger']}) прислал сообщение:\n{message.text}"
            t_bot.send_message(settings["main_id"], out, reply_markup=keyboard)
            return True
        else: # Диалог
            tolker = db_users.find_one({"system id": user['operator']['active session']})
            if message.content_type == 'photo':
                if tolker["messenger"] == "telegram":
                    if user["admin"] >= 1:
                        t_bot.send_photo(tolker["_id"], message.photo[-1].file_id, caption=user['name'])
                    else:
                        t_bot.send_photo(tolker["_id"], message.photo[-1].file_id, caption=f"{user['name']}, ({user['messenger']}) прислал изображение")
                    return True
                elif tolker["messenger"] == "viber":
                    photo_id = t_bot.get_file(message.photo[-1].file_id)
                    photo_name = photo_id.file_id
                    file = f'https://api.telegram.org/file/bot{cfg.token}/{photo_id.file_path}'
                    h = httplib2.Http('.cache')
                    response, content = h.request(file)
                    out = open(f'./pic/{photo_name}.jpg', 'wb')
                    out.write(content)
                    out.close()
                    viber = Api(BotConfiguration(name=user['operator']['name'], avatar=cfg.v_avatar, auth_token=cfg.v_token))
                    viber.send_messages(tolker['_id'], [
                        PictureMessage(media=f"https://bot.vizit-net.com/new/pics/{photo_name}.jpg")])
                    out = f'''Изображение отправлено {tolker['name']} ({tolker['messenger']})'''
                    t_bot.send_message(message.chat.id, out)
                    return True
            if tolker["messenger"] == "telegram":
                answer = f"{user['name']}, ({user['messenger']}) прислал сообщение:\n{message.text}"
                if user["admin"] >= 1:
                    answer = f"{user['operator']['name']}\n{message.text}"
                t_bot.send_message(tolker['_id'], answer)
                return True
            elif tolker["messenger"] == "viber":
                try:
                    viber = Api(BotConfiguration(name=user['operator']['name'], avatar=cfg.v_avatar, auth_token=cfg.v_token))
                    viber.send_messages(tolker["_id"], [TextMessage(text=message.text)])
                except Exception as error:
                    logging.exception(f"Error: {error}")
                return True
    return False