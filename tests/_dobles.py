# -*- coding: utf-8 -*-
"""Objetos falsos que imitan lo que python-telegram-bot le pasa a un handler,
para poder ejercitar los flujos sin hablar con Telegram ni con el proveedor."""
import asyncio


class FakeMessage:
    def __init__(self, mid=50, text=""):
        self.message_id = mid
        self.text = text
        self.respuestas = []
        self.teclados = []

    async def reply_text(self, texto, reply_markup=None, **kw):
        self.respuestas.append(texto)
        self.teclados.append(reply_markup)
        return self

    async def edit_text(self, texto, reply_markup=None, **kw):
        """En python-telegram-bot, reply_text() devuelve un Message que se
        puede editar después. Aquí se guarda igual que una respuesta más."""
        self.respuestas.append(texto)
        self.teclados.append(reply_markup)
        return self

    async def reply_photo(self, file_id, caption="", reply_markup=None, **kw):
        self.respuestas.append(caption)
        self.teclados.append(reply_markup)
        self.fotos_enviadas = getattr(self, "fotos_enviadas", [])
        self.fotos_enviadas.append(file_id)
        return self

    def botones(self):
        """Todos los callback_data de los botones que se enviaron."""
        datos = []
        for kb in self.teclados:
            if kb is None:
                continue
            for fila in kb.inline_keyboard:
                for b in fila:
                    datos.append(b.callback_data)
        return datos


class FakeQuery:
    def __init__(self, data, mid=50):
        self.data = data
        self.message = FakeMessage(mid)
        self.ediciones = []
        self.alertas = []

    async def answer(self, text=None, **kw):
        if text:
            self.alertas.append(text)

    async def edit_message_text(self, texto, reply_markup=None, **kw):
        self.ediciones.append(texto)
        if reply_markup is not None:
            self.message.teclados.append(reply_markup)

    async def edit_message_caption(self, caption, reply_markup=None, **kw):
        """El aviso de un comprobante es una foto: se edita su pie."""
        self.ediciones.append(caption)
        if reply_markup is not None:
            self.message.teclados.append(reply_markup)


class FakeUser:
    def __init__(self, uid=1, username="cliente", first_name="Ana"):
        self.id = uid
        self.username = username
        self.first_name = first_name


class FakeUpdate:
    """Sirve tanto para un mensaje como para un toque de botón."""

    def __init__(self, *, message=None, query=None, user=None):
        self.message = message
        self.callback_query = query
        self.effective_user = user or FakeUser()

    @property
    def effective_message(self):
        return self.message or (self.callback_query.message if self.callback_query else None)


class FakeBot:
    def __init__(self):
        self.enviados = []

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        self.enviados.append((chat_id, text, reply_markup))

    async def send_photo(self, chat_id, file_id, caption="", reply_markup=None, **kw):
        self.enviados.append((chat_id, caption, reply_markup))
        self.fotos = getattr(self, "fotos", [])
        self.fotos.append((chat_id, file_id))

    def textos_a(self, chat_id):
        return [t for cid, t, _ in self.enviados if cid == chat_id]


class FakeContext:
    def __init__(self, args=None):
        self.user_data = {}
        self.bot = FakeBot()
        self.args = args or []


def correr(coro):
    return asyncio.run(coro)
