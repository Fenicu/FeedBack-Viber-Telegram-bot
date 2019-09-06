import telebot
from flask import Flask, request, Response, abort
import sys
import logging as lgoff
import config as cfg
import MessageBox
import re
from threading import Timer
from viberbot import Api
from viberbot.api.bot_configuration import BotConfiguration
from viberbot.api.messages.text_message import TextMessage
from viberbot.api.messages.keyboard_message import KeyboardMessage
from viberbot.api.viber_requests import ViberConversationStartedRequest
from viberbot.api.viber_requests import ViberMessageRequest
from loguru import logger as logging
from pymongo import MongoClient
from telebot import types
contents = ["text", "sticker", "document", "photo", "audio", "voice"]
client = MongoClient()
db = client.FeedBot
db_users = db.users
db_settings = db.settings
logging.remove()
logging.add(sys.stdout, colorize=True, format="<green>{time:DD.MM.YY H:mm:ss}</green> " \
                "| <yellow><b>{level}</b></yellow> | <magenta>{file}:{line}</magenta> | <cyan>{message}</cyan>")
logging.add("./log/bot.log", rotation="50 MB", format="{time:DD.MM.YY H:mm:ss} | {level} | {file}:{line} | {message}")
bot = telebot.TeleBot(cfg.token)
app = Flask(__name__)
viber = Api(BotConfiguration(
    name='BotName',
    avatar=cfg.v_avatar,
    auth_token=cfg.v_token
))

@app.route('/telega', methods=['POST'])
def TelegramIncoming():
    try:
        if not request.headers.get('content-type') == 'application/json':
            abort(403)
        logging.debug(f"Telegram data: {request.get_data().decode('utf-8')}")
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        if update.message is not None:
            user_update(update.message, 'telegram')
        #user = db_users.find_one({"_id": update.message.from_user.id})
        #result = MessageBox.Message(bot, viber, update.message, user)
        bot.process_new_updates([update])
    except KeyError:
        return abort(404)
    except Exception as Error:
        logging.error(Error)
        return abort(404)
    finally:
        return Response(status=200)

@app.route('/viber/', methods=['POST'])
def ViberIncoming():
    try:
        if not viber.verify_signature(request.get_data(), request.headers.get('X-Viber-Content-Signature')):
            return Response(status=403)
        logging.debug(f"Viber data: {request.get_data().decode('utf-8')}")
        viber_request = viber.parse_request(request.get_data())
        if viber_request.event_type == "message":
            user_update(viber_request, 'viber')
        if (isinstance(viber_request, ViberConversationStartedRequest)) or (isinstance(viber_request, ViberMessageRequest) and \
                                        viber_request.message.text.lower() == "привет"):
            # Пользователь который только что тыкнул на бота или написал привет
            out = """Welcome message Viber"""
            try:
                viber.send_messages(viber_request.user.id, [TextMessage(text=out)])
            except:
                viber.send_messages(viber_request.sender.id, [TextMessage(text=out)])
        elif isinstance(viber_request, ViberMessageRequest):
            # Пользователь написал что-то боту
            user = db_users.find_one({"_id": viber_request.sender.id})
            MessageBox.Message(bot, viber, viber_request, user)
    except Exception as Error:
        logging.error(Error)
        return abort(404)
    finally:
        return Response(status=200)

def user_update(data, messenger):
    if messenger == "telegram":
        name = data.from_user.first_name
        if data.from_user.last_name:
            name += " " + data.from_user.last_name
        if db_users.find_one({"_id": data.from_user.id}):
            user = db_users.find_one({"_id": data.from_user.id})
            if user["name"] != name:
                user["name"] = name
                db_users.replace_one({"_id": data.from_user.id}, user, True)
            return
        base_json = {
            "_id": data.from_user.id,
            "system id": db_users.find().count() + 100,
            "messenger": messenger,
            "name": name,
            "fsm": 0,
            "admin": 0,
            "operator": {
                "name": name,
                "active session": None,
                "sessions": None}
        }
        db_users.insert_one(base_json)
        logging.info('Записан новый пользователь Telegram')
        return
    elif messenger == "viber":
        if db_users.find_one({"_id": data.sender.id}):
            user = db_users.find_one({"_id": data.sender.id})
            if user["name"] != data.sender.name:
                user["name"] = data.sender.name
                db_users.replace_one({"_id": data.sender.id}, user, True)
            return
        base_json = {
            "_id": data.sender.id,
            "system id": db_users.find().count() + 100,
            "messenger": messenger,
            "name": data.sender.name,
            "fsm": 0,
            "admin": 0,
            "operator": {
                "name": data.sender.name,
                "active session": None,
                "sessions": None}
        }
        db_users.insert_one(base_json)
        logging.info('Записан новый пользователь Viber')
        return

class filter_handler:
    def __init__(self, message):
        self.message = message
        self.user = db_users.find_one({"_id": self.message.from_user.id})

    def level_access(self, need):
        if self.user["admin"] >= need:
            return True
        return False

@bot.message_handler(func=lambda message: filter_handler(message).level_access(1) and message.chat.type == 'private', commands=["start", "help"])
def AdminStart(message):
    if not re.search("\/start (\d+)", message.text):
        markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
        buttons = [types.KeyboardButton('🎓 Персонал')]
        buttons.append(types.KeyboardButton('🔥 Сессии'))
        buttons.append(types.KeyboardButton('⚙️ Сменить имя'))
        markup.add(*buttons)
        bot.send_message(message.chat.id, 'Панель управления', reply_markup=markup)
        return
    system_id = int(re.search("(\d+)", message.text).group(1))
    user = db_users.find_one({"_id": message.from_user.id})
    tolker = db_users.find_one({"system id": system_id})
    if tolker['operator']['active session'] is not None:
        bot.send_message(message.chat.id, 'Пользователь сейчас занят другим оператором')
        return
    tolker['operator']['active session'] = user['system id']
    if user['operator']["sessions"] is None:
        user['operator']["sessions"] = []
    if user['operator']['active session'] is None:
        user['operator']['active session'] = system_id
        if system_id in user['operator']["sessions"]:
            user['operator']["sessions"].remove(system_id)
        db_users.replace_one({"_id": message.from_user.id}, user, True)
        db_users.replace_one({"system id": system_id}, tolker, True)
        bot.send_message(message.chat.id, f'Диалог с {tolker["name"]} активен')
        if tolker["messenger"] == "viber":
            viber = Api(BotConfiguration(name=user['operator']['name'], avatar=cfg.v_avatar, auth_token=cfg.v_token))
            viber.send_messages(tolker["_id"], [TextMessage(text='Оператор подключился')])
        elif tolker["messenger"] == "telegram":
            bot.send_message(tolker["_id"], f"{user['operator']['name']} Оператор подключился")
        return
    if system_id in user['operator']["sessions"]:
        user['operator']["sessions"].remove(system_id)
    if user['operator']['active session'] is not None:
        user['operator']["sessions"].append(user['operator']['active session'])
    user['operator']['active session'] = system_id
    db_users.replace_one({"_id": message.from_user.id}, user, True)
    db_users.replace_one({"system id": system_id}, tolker, True)
    bot.send_message(message.chat.id, f'Диалог с {tolker["name"]} активен')
    if tolker["messenger"] == "viber":
        viber = Api(BotConfiguration(name=user['operator']['name'], avatar=cfg.v_avatar, auth_token=cfg.v_token))
        viber.send_messages(tolker["_id"], [TextMessage(text='Оператор подключился')])
    elif tolker["messenger"] == "telegram":
        bot.send_message(tolker["_id"], f"{user['operator']['name']} Оператор подключился")

@bot.message_handler(func=lambda message: message.chat.type == 'private', commands=["start", "help"])
def BaseStart(message):
    out = """Welcome Message Telegram"""
    bot.send_message(message.chat.id, out, parse_mode="HTML", disable_web_page_preview=True)

@bot.message_handler(func=lambda message: filter_handler(message).level_access(1) and message.chat.type == 'private', regexp='⚙️ Сменить имя')
def StaffChName(message):
    user = db_users.find_one({"_id": message.from_user.id})
    user['fsm'] = 1
    db_users.replace_one({"_id": message.from_user.id}, user, True)
    bot.send_message(message.chat.id, 'Напиши новое имя')

@bot.message_handler(func=lambda message: filter_handler(message).level_access(1) and message.chat.type == 'private', regexp='🎓 Персонал')
def Staff(message):
    user = db_users.find_one({"_id": message.from_user.id})
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    buttons = [types.KeyboardButton('🎓 Персонал')]
    buttons.append(types.KeyboardButton('🔥 Сессии'))
    buttons.append(types.KeyboardButton('⚙️ Сменить имя'))
    markup.add(*buttons)
    admins = db_users.find({"admin": {'$gt': 0}})
    out = ""
    if user['admin'] > 1:
        out += "Чтобы назначить нового человека:\n/add LVL ID\nгде LVL - уровень доступа " \
            "(1 - оператор, 2 - админ)\nID - тг id\nнапример /add 2 267519921\nТакже можно в чате реплаем на нужного человека /add LVL\n\n"
    out += "Текущий персонал:\n"
    for i in admins:
        if user['admin'] > 1:
            if i['system id'] == user['system id']:
                out += f"Уровень доступа {i['admin']} | {i['name']}\n"
            else:
                out += f"Уровень доступа {i['admin']} | {i['name']} /del_{i['system id']}\n"
        else:
            out += f"Уровень доступа {i['admin']} | {i['name']}\n"
    bot.send_message(message.chat.id, out, reply_markup=markup)

@bot.message_handler(func=lambda message: filter_handler(message).level_access(2) and message.chat.type == 'private', regexp='/del_(\d+)')
def StaffDel(message):
    system_id = int(re.search("(\d+)", message.text).group(1))
    user = db_users.find_one({"system id": system_id})
    user['admin'] = 0
    db_users.replace_one({"system id": system_id}, user, True)
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    buttons = [types.KeyboardButton('🎓 Персонал')]
    buttons.append(types.KeyboardButton('🔥 Сессии'))
    buttons.append(types.KeyboardButton('⚙️ Сменить имя'))
    markup.add(*buttons)
    bot.send_message(message.chat.id, "Пользователь разжалован", reply_markup=markup)

@bot.message_handler(func=lambda message: filter_handler(message).level_access(2) and message.chat.type == 'private', regexp='\/add (\d+) (\d+)')
def StaffNewPrivate(message):
    _id = int(re.search("(\d+) (\d+)", message.text).group(2))
    permlvl = int(re.search("(\d+) (\d+)", message.text).group(1))
    if not db_users.find_one({"_id": _id}):
        bot.send_message(message.chat.id, "Пользователь не найден")
        return
    user = db_users.find_one({"_id": _id})
    user['admin'] = permlvl
    db_users.replace_one({"_id": _id}, user, True)
    bot.send_message(message.chat.id, "Права обновлены")

@bot.message_handler(func=lambda message: filter_handler(message).level_access(2) and \
                message.chat.type in ['supergroup','group'] and message.reply_to_message, regexp='\/add (\d+)')
def StaffNew(message):
    permlvl = int(re.search("(\d+)", message.text).group(1))
    if not db_users.find_one({"_id": message.reply_to_message.from_user.id}):
        bot.send_message(message.chat.id, "Пользователь не найден")
        return
    user = db_users.find_one({"_id": _id})
    user['admin'] = permlvl
    db_users.replace_one({"_id": _id}, user, True)
    bot.send_message(message.chat.id, "Права обновлены")
@bot.message_handler(func=lambda message: filter_handler(message).level_access(1) and message.chat.type == 'private', regexp='🔥 Сессии')
def Sessions(message):
    user = db_users.find_one({"_id": message.from_user.id})
    out = "a - Активировать\nh - Свернуть\nc - Закрыть\n\n"
    if user['operator']['active session'] is not None:
        tolker = db_users.find_one({"system id": user['operator']['active session']})
        t_id = user['operator']['active session']
        out += f"🔥Активная сессия c {tolker['name']} ({tolker['messenger']})\n    /h_{t_id} /c_{t_id}\n\n"
    if user['operator']["sessions"] is not None:
        for session in user['operator']["sessions"]:
            tolker = db_users.find_one({"system id": session})
            out += f"сессия c {tolker['name']} ({tolker['messenger']})\n    /a_{session} /c_{session}\n\n"
    bot.send_message(message.chat.id, out)

@bot.message_handler(func=lambda message: filter_handler(message).level_access(1) and message.chat.type == 'private', regexp='/a_(\d+)')
def SessionActive(message):
    system_id = int(re.search("(\d+)", message.text).group(1))
    if not db_users.find_one({"system id": system_id}):
        bot.send_message(message.chat.id, 'Такого пользователя нет')
        return
    tolker = db_users.find_one({"system id": system_id})
    user = db_users.find_one({"_id": message.from_user.id})
    if user['operator']["sessions"] is None:
        user['operator']["sessions"] = []
    if user['operator']['active session'] is None:
        user['operator']['active session'] = system_id
        if system_id in user['operator']["sessions"]:
            user['operator']["sessions"].remove(system_id)
        if tolker['operator']['active session'] is None:
            tolker['operator']['active session'] = user['system id']
            db_users.replace_one({"system id": system_id}, tolker, True)
        db_users.replace_one({"_id": message.from_user.id}, user, True)
        bot.send_message(message.chat.id, f'Диалог с {tolker["name"]} активен')
        return
    if system_id in user['operator']["sessions"]:
        user['operator']["sessions"].remove(system_id)
    if user['operator']['active session'] is not None:
        user['operator']["sessions"].append(user['operator']['active session'])
    user['operator']['active session'] = system_id
    if tolker['operator']['active session'] is None:
        tolker['operator']['active session'] = user['system id']
        db_users.replace_one({"system id": system_id}, tolker, True)
    db_users.replace_one({"_id": message.from_user.id}, user, True)
    bot.send_message(message.chat.id, f'Диалог с {tolker["name"]} активен')

@bot.message_handler(func=lambda message: filter_handler(message).level_access(1) and message.chat.type == 'private', regexp='/h_(\d+)')
def SessionHide(message):
    system_id = int(re.search("(\d+)", message.text).group(1))
    user = db_users.find_one({"_id": message.from_user.id})
    if not db_users.find_one({"system id": system_id}):
        bot.send_message(message.chat.id, 'Такого пользователя нет')
        return
    tolker = db_users.find_one({"system id": system_id})
    if user['operator']['active session'] is None:
        bot.send_message(message.chat.id, "Активной сессии нет")
        return
    if user['operator']['active session'] != system_id:
        bot.send_message(message.chat.id, "Такой активной сессии нет")
        return
    if user['operator']["sessions"] is None:
        user['operator']["sessions"] = []
    user['operator']["sessions"].append(user['operator']['active session'])
    user['operator']['active session'] = None
    db_users.replace_one({"_id": message.from_user.id}, user, True)
    bot.send_message(message.chat.id, f'Сессия с {tolker["name"]} свёрнута')

@bot.message_handler(func=lambda message: filter_handler(message).level_access(1) and message.chat.type == 'private', regexp='/c_(\d+)')
def SessionClose(message):
    system_id = int(re.search("(\d+)", message.text).group(1))
    user = db_users.find_one({"_id": message.from_user.id})
    if not db_users.find_one({"system id": system_id}):
        bot.send_message(message.chat.id, 'Такого пользователя нет')
        return
    tolker = db_users.find_one({"system id": system_id})
    if user['operator']['active session'] == system_id:
        user['operator']['active session'] = None
        tolker['operator']['active session'] = None
        db_users.replace_one({"_id": message.from_user.id}, user, True)
        db_users.replace_one({"_id": tolker["_id"]}, tolker, True)
        bot.send_message(message.chat.id, f'Активная сессия с {tolker["name"]} закрыта')
        if tolker["messenger"] == "viber":
            viber = Api(BotConfiguration(name=user['operator']['name'], avatar=cfg.v_avatar, auth_token=cfg.v_token))
            viber.send_messages(tolker["_id"], [TextMessage(text='Оператор отключился')])
        elif tolker["messenger"] == "telegram":
            bot.send_message(tolker["_id"], f"{user['operator']['name']}\nОтключился")
        return
    if system_id in user['operator']["sessions"]:
        user['operator']['sessions'].remove(system_id)
        tolker['operator']['active session'] = None
        if len(user['operator']["sessions"]) == 0:
            user['operator']["sessions"] = None
        db_users.replace_one({"_id": message.from_user.id}, user, True)
        db_users.replace_one({"_id": tolker["_id"]}, tolker, True)
        bot.send_message(message.chat.id, f'Сессия с {tolker["name"]} закрыта')
        if tolker["messenger"] == "viber":
            viber = Api(BotConfiguration(name=user['operator']['name'], avatar=cfg.v_avatar, auth_token=cfg.v_token))
            viber.send_messages(tolker["_id"], [TextMessage(text='Оператор отключился')])
        elif tolker["messenger"] == "telegram":
            bot.send_message(tolker["_id"], f"{user['operator']['name']}\nОтключился")
        return

@bot.message_handler(func=lambda message: message.chat.type == 'private', content_types=["text", "photo"])
def all(message): #
    user = db_users.find_one({"_id": message.from_user.id})
    if user['fsm'] == 1 and message.text is not None:
        user['fsm'] = 0
        user['operator']['name'] = message.text
        db_users.replace_one({"_id": message.from_user.id}, user, True)
        bot.send_message(message.chat.id, f'Будем звать тебя {message.text}')
        return
    MessageBox.Message(bot, viber, message, user)






def set_hook():
    logging.info(f'sets webhooks')
    url_viber = 'https://bot.vizit-net.com/viber/'
    url_telegram = 'https://bot.vizit-net.com/telega'
    try:
        viber.set_webhook(url_viber)
        logging.info(f'webhook viber true')
        bot.set_webhook(url=url_telegram, allowed_updates=['message'])
        logging.info(f'webhook telegram true')
    except Exception as error:
        logging.error(error)

if __name__ == "__main__":
    log = lgoff.getLogger('werkzeug')
    log.disabled = True
    Timer(3, set_hook).start()
    logging.info(f'bot starting')
    app.run(host='localhost', port=5564, debug=False)