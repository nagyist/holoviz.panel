
import datetime

from contextlib import ExitStack
from dataclasses import dataclass
from inspect import isawaitable
from io import BytesIO
from tempfile import NamedTemporaryFile
from typing import (
    Any, BinaryIO, ClassVar, List, Mapping, Optional, Type, Union,
)

import param

from ..io.resources import CDN_DIST
from ..layout import (
    Column, ListPanel, Row, Tabs,
)
from ..layout.card import Card
from ..pane.base import panel as _panel
from ..pane.image import PDF, Image
from ..pane.markup import HTML, DataFrame
from ..pane.media import Audio, Video
from ..reactive import ReactiveHTML
from ..viewable import Viewable
from .base import CompositeWidget, Widget
from .button import Button
from .indicators import LoadingSpinner
from .input import FileInput, TextInput


@dataclass
class _FileInputMessage:
    contents: bytes
    file_name: str
    mime_type: str


class ChatReactionIcons(ReactiveHTML):

    value = param.List(doc="The selected reactions.")

    options = param.Dict(default={"favorite": "heart"}, doc="""
        A key-value pair of reaction values and their corresponding tabler icon names
        found on https://tabler-icons.io.""")

    icon_size = param.String(default="15px", doc="""The size of each icon.""")

    active_icons = param.Dict(default={}, doc="""
        The mapping of reactions to their corresponding active icon names;
        if not set, the active icon name will default to its "filled" version.""")

    _icon_base_url = param.String("https://tabler-icons.io/static/tabler-icons/icons/")

    _template = """
        <div id="reaction-icons" class="reaction-icons">
            {% for reaction, icon_name in options.items() %}
            <img id="icon-{{ loop.index0 }}" alt="{{ reaction }}"
                {% if reaction in value and reaction in active_icons %}
                src="${_icon_base_url}{{ active_icons[reaction] }}.svg"
                {% elif reaction in value %}
                src="${_icon_base_url}{{ icon_name }}-filled.svg"
                {% else %}
                src="${_icon_base_url}{{ icon_name }}.svg"
                {% endif %}
                style="width: ${icon_size}; height: ${icon_size}; cursor: pointer;"
                onclick="${script('update_value')}">
            </img>
            {% endfor %}
        </div>
    """

    _scripts = {
        "update_value": """
            const reaction = event.target.alt;
            const icon_name = data.options[reaction];
            if (data.value.includes(reaction)) {
                data.value = data.value.filter(r => r !== reaction);
                event.target.src = data._icon_base_url + icon_name + ".svg";
            } else {
                data.value = [...data.value, reaction];
                if (reaction in data.active_icons) {
                    event.target.src = data._icon_base_url + data.active_icons[reaction] + ".svg";
                } else {
                    event.target.src = data._icon_base_url + icon_name + "-filled.svg";
                }
            }
        """
    }

    _stylesheets: ClassVar[List[str]] = [
        f'{CDN_DIST}css/chat_reaction_icons.css'
    ]


class ChatEntry(ReactiveHTML):

    value = param.Parameter(doc="""
        The message contents. Can be a string, pane, widget, layout, etc.""")

    user = param.Parameter(default="User", doc="""
        Name of the user who sent the message.""")

    avatar = param.ClassSelector(class_=(str, BinaryIO), doc="""
        The avatar to use for the user. Can be a single character text, an emoji,
        a URL, a file path, or a binary IO. If not set, uses the first letter
        of the name.""")

    reactions = param.List(doc="""
        Reactions to associate with the message.""")

    timestamp = param.Date(
        default=datetime.datetime.utcnow(), doc="""
        Timestamp of the message. Defaults to the instantiation time.""")

    reaction_icons = param.ClassSelector(class_=ChatReactionIcons, doc="""
        The available reaction icons to click on.""")

    timestamp_format = param.String(default="%H:%M", doc="The timestamp format.")

    show_avatar = param.Boolean(default=True, doc="Whether to show the avatar.")

    show_user = param.Boolean(default=True, doc="Whether to show the name.")

    show_timestamp = param.Boolean(default=True, doc="Whether to show the timestamp.")

    _avatar_pane = param.ClassSelector(class_=(HTML, Image), doc="The rendered avatar pane.")

    _user_pane = param.ClassSelector(class_=HTML, doc="The rendered user pane.")

    _value_viewable = param.ClassSelector(class_=Viewable, doc="The rendered value viewable.")

    _template = """
    <div class="chat-entry">

        {% if show_avatar %}
        <span id="avatar" class="avatar">${_avatar_pane}</span>
        {% endif %}

        <div class="right">
            {% if show_user %}
            <span id="name" class="name">${_user_pane}</span>
            {% endif %}

            <div id="message" class="message">
                ${_value_viewable}
            </div>

            <div id="footer" class="footer">
                {% if show_timestamp %}
                <span id="timestamp" class="timestamp">
                    {{ timestamp.strftime(timestamp_format) }}
                </span>
                {% endif %}
                {% if reaction_icons %}
                ${reaction_icons}
                {% endif %}
            </div>
        </div>
    </div>
    """

    _stylesheets: ClassVar[List[str]] = [
        f'{CDN_DIST}css/chat_entry.css'
    ]

    _exit_stack: ExitStack = None

    def __init__(self, **params):
        self._exit_stack = ExitStack()

        if params.get("reaction_icons") is None:
            params["reaction_icons"] = ChatReactionIcons()
        elif isinstance(params["reaction_icons"], dict):
            params["reaction_icons"] = ChatReactionIcons(options=params["reaction_icons"])
        super().__init__(**params)
        self.reaction_icons.link(self, value="reactions", bidirectional=True)

    @param.depends('avatar', watch=True, on_init=True)
    def _render_avatar(self) -> None:
        """
        Render the avatar pane as some HTML text or Image pane.
        """
        avatar = self.avatar
        if not avatar and self.user:
            avatar = self.user[0]

        if len(avatar) == 1:
            self._avatar_pane = HTML(avatar, css_classes=["avatar"])
        else:
            self._avatar_pane = Image(
                avatar, width=35, height=35, css_classes=["avatar"]
            )

    def _cleanup(self) -> None:
        """
        Cleanup the exit stack.
        """
        if self._exit_stack is not None:
            self._exit_stack.close()
            self._exit_stack = None
        super()._cleanup()

    @param.depends('user', watch=True, on_init=True)
    def _render_user(self) -> None:
        """
        Render the user pane as some HTML text or Image pane.
        """
        self._user_pane = HTML(self.user, css_classes=["name"])

    @param.depends('value', watch=True, on_init=True)
    def _render_value(self) -> None:
        """
        Render the value pane as some HTML text or Image pane.
        """
        value = self.value
        if isinstance(value, str):
            self._value_viewable = HTML(value, css_classes=["value"])
        elif isinstance(value, Viewable):
            self._value_viewable = value
        else:
            if isinstance(value, _FileInputMessage):
                contents = value.contents
                mime_type = value.mime_type
                file_name = value.file_name
                value, message_callable = self._get_value_callable(
                    contents, mime_type, file_name=file_name
                )
            else:
                try:
                    import magic
                    mime_type = magic.from_buffer(value, mime=True)
                    value, message_callable = self._get_value_callable(
                        value, mime_type, file_name=None
                    )
                except Exception:
                    message_callable = _panel

            try:
                if isinstance(message_callable, Widget):
                    value_viewable = message_callable(value=value)
                else:
                    value_viewable = message_callable(value)
            except ValueError:
                value_viewable = _panel(value)
            self._value_viewable = value_viewable

    def _get_value_callable(self, contents, mime_type, file_name=None):
        message_callable = _panel
        if mime_type == 'application/pdf':
            contents = self._exit_stack.enter_context(
                BytesIO(contents)
            )
            message_callable = PDF
        elif mime_type.startswith('audio/'):
            f = self._exit_stack.enter_context(
                NamedTemporaryFile(suffix=".mp3", delete=False)
            )
            f.write(contents)
            f.seek(0)
            contents = f.name
            message_callable = Audio
        elif mime_type.startswith('video/'):
            contents = self._exit_stack.enter_context(
                BytesIO(contents)
            )
            message_callable = Video
        elif mime_type.startswith('image/'):
            contents = self._exit_stack.enter_context(
                BytesIO(contents)
            )
            message_callable = Image
        elif mime_type.endswith("/csv"):
            import pandas as pd
            with BytesIO(contents) as buf:
                contents = pd.read_csv(buf)
            message_callable = DataFrame
        elif file_name is not None:
            contents = f"`{file_name}`"
        return contents, message_callable

class ChatCard(Card):

    callback = param.Callable(doc="""
        Callback to execute when a user sends a message.
        The signature must include the previous message value `contents`, the previous `user` name,
        and the `chat_card` instance.""")

    placeholder = param.Parameter(doc="""
        Placeholder to display while the callback is running.
        If not set, defaults to a LoadingSpinner.""")

    show_placeholder = param.Boolean(default=True, doc="""
        Whether to show the placeholder while the callback is running.""")

    auto_scroll_limit = param.Integer(default=100, bounds=(0, None), doc="""
        Max pixel distance from the latest object in the Column to
        activate automatic scrolling upon update. Setting to 0
        disables auto-scrolling.""")

    scroll_button_threshold = param.Integer(default=50, bounds=(0, None), doc="""
        Min pixel distance from the latest object in the Column to
        display the scroll button. Setting to 0
        disables the scroll button.""")

    view_latest = param.Boolean(default=True, doc="""
        Whether to scroll to the latest object on init. If not
        enabled the view will be on the first object.""")

    chat_entry_params = param.Dict(default={}, doc="""
        Params to pass to ChatEntry, like `reaction_icons`, `timestamp_format`,
        `show_avatar`, `show_user`, and `show_timestamp`.""")

    _disabled = param.Boolean(default=False, doc="""
        Whether the chat card is disabled.""")

    _rename: ClassVar[Mapping[str, None]] = dict(
        Column._rename, **{
        'callback': None,
        'placeholder': None,
        'show_placeholder': None,
        'auto_scroll_limit': None,
        'scroll_button_threshold': None,
        'view_latest': None,
        'chat_entry_params': None,
        '_disabled': None
    })

    _stylesheets: ClassVar[List[str]] = [
        f'{CDN_DIST}css/chat_card.css'
    ]

    def __init__(self, *objects: Any, **params: Any):
        params.update({
            "collapsed": False,
            "collapsible": False,
            "css_classes": ['chat-card'],
            "header_css_classes": ['chat-card-header'],
            "title_css_classes": ['chat-card-title'],
        })
        chat_log_params = {
            p: getattr(self, p)
            for p in Column.param
            if (
                p in ChatCard.param and
                p != "name" and
                getattr(self, p) is not None
            )
        }
        chat_log_params["styles"] = {"background": "transparent"}
        objects = params.pop("objects", None) or objects

        sizing_mode = chat_log_params.get("sizing_mode", "stretch_width")
        chat_log_params["sizing_mode"] = sizing_mode
        if sizing_mode is None:
            chat_log_params["sizing_mode"] = "stretch_width"
        chat_log_params["objects"] = objects
        chat_log_height = (
            chat_log_params.get("max_height") or
            chat_log_params.get("height", 450)
        )
        if "height" in sizing_mode or "both" in sizing_mode:
            chat_log_params["max_height"] = chat_log_height
        else:
            chat_log_params["height"] = chat_log_height
        chat_log_params["margin"] = 0

        self._chat_log = Column(**chat_log_params)
        self._respond_trigger = Button(visible=False)
        self._respond_trigger.on_click(self._execute_callback)
        super().__init__(self._chat_log, **params)

        if self.placeholder is None:
            self.placeholder = LoadingSpinner(
                width=10,
                height=10,
                value=True,
                margin=(10, 0, 10, 3)
            )

    @param.depends("title", "header", watch=True, on_init=True)
    def _hide_header(self):
        """
        Hide the header if there is no title or header.
        """
        if not self.title and not self.header:
            self.hide_header = True
        else:
            self.hide_header = False

    def _update_entry(self, message: Any, entry: ChatEntry) -> bool:
        """
        Update the placeholder entry with the response.
        """
        if isinstance(message, dict):
            message_param_values = message
        else:
            message_param_values =  {"value": message}

        if entry is None:
            entry = ChatEntry(**message_param_values, **self.chat_entry_params)
            self._chat_log.append(entry)
        else:
            entry.param.update(**message_param_values)
        return entry

    async def _execute_callback(self, _):
        """
        Execute the callback and send the response.
        """
        if self.callback is None:
            return

        try:
            self._disabled = True
            entry = self._chat_log[-1]

            if self.show_placeholder:
                response_entry = self._update_entry({
                    "value": self.placeholder,
                    "user": "&nbsp;",
                    "avatar": " ",
                }, None)
            else:
                response_entry = None

            value = entry._value_viewable
            if hasattr(value, "object"):
                contents = value.object
            elif hasattr(value, "objects"):
                contents = value.objects
            elif hasattr(value, "value"):
                contents = value.value
            else:
                contents = value

            response = self.callback(contents, entry.user, self)

            if hasattr(response, "__aiter__"):
                async for chunk in response:
                    response_entry = self._update_entry(chunk, response_entry)
            elif hasattr(response, "__iter__"):
                for chunk in response:
                    response_entry = self._update_entry(chunk, response_entry)
            elif isawaitable(self.callback):
                response_entry = self._update_entry(await response, response_entry)
            else:
                response_entry = self._update_entry(response, response_entry)
        finally:
            self._disabled = False

    def send(
        self,
        message: Union[ChatEntry, dict, str],
        respond: bool = True,
    ) -> None:
        """
        Send a message to the Chat Card and
        execute the callback if provided.

        Parameters
        ----------
        message : Union[ChatEntry, dict, str]
            The message to send.
        """
        if isinstance(message, str):
            message = {"value": message}

        if isinstance(message, dict):
            entry = ChatEntry(**message, **self.chat_entry_params)
        else:
            entry = message

        self._chat_log.append(entry)
        if respond:
            self._respond_trigger.param.trigger("clicks")

class ChatInterface(CompositeWidget):
    """
    High level widget that contains the chat log and the chat input.
    """

    value = param.ClassSelector(class_=ChatCard, doc="The ChatCard widget.")

    widgets = param.List(default=[TextInput], doc="""
        Widgets to use for the input.""")

    user = param.String(default="You", doc="Name of the ChatInterface user.")

    avatar = param.ClassSelector(class_=(str, BinaryIO), doc="""
        The avatar to use for the user. Can be a single character text, an emoji,
        a URL, a file path, or a binary IO. If not set, uses the first letter
        of the name.""")

    _composite_type: ClassVar[Type[ListPanel]] = Column

    def __init__(self, **params):
        super().__init__(**params)
        if self.value is None:
            self.value = ChatCard(objects=[])

        input_layout = self._init_widgets()
        self.link(self.value, disabled="_disabled", bidirectional=True)
        self._composite[:] = [self.value, input_layout]

    def _link_disabled_loading(self, obj: Viewable):
        """
        Link the disabled and loading attributes of the chat box to the
        given object.
        """
        for key in ["disabled", "loading"]:
            setattr(obj, key, getattr(self, key))
            self.link(obj, **{key: key})

    def _init_widgets(self) -> Union[Tabs, Row]:
        """
        Initialize the input widgets.

        Returns
        -------
        The input widgets.
        """
        self._widgets = {}
        for widget in self.widgets:
            key = widget.name or widget.__class__.__name__
            if isinstance(widget, type):  # check if instantiated
                widget = widget()
            self._widgets[key] = widget

        input_layout = Tabs()
        for name, widget in self._widgets.items():
            widget.sizing_mode = "stretch_width"
            # for longer form messages, like TextArea / Ace, don't
            # submit when clicking away; only if they manually click
            # the send button
            if isinstance(widget, TextInput):
                widget.param.watch(self._enter_input, "value")
            send_button = Button(
                name="Send",
                button_type="default",
                sizing_mode="stretch_width",
                max_width=100,
                height=35,
            )
            send_button.on_click(self._enter_input)
            self._link_disabled_loading(send_button)
            message_row = Row(widget, send_button)
            input_layout.append((name, message_row))

        if len(self._widgets) == 1:
            input_layout = input_layout[0]  # if only a single input, don't use tabs

        return input_layout

    async def _enter_input(self, _: Optional[param.parameterized.Event] = None) -> None:
        """
        Send the input when the user presses Enter.
        """
        # wait until the chat card's callback is done executing
        if self.disabled:
            return

        for widget in self._widgets.values():
            if hasattr(widget, "value_input"):
                widget.value_input = ""
            value = widget.value
            if value:
                if isinstance(widget, FileInput):
                    value = _FileInputMessage(
                        contents=value,
                        mime_type=widget.mime_type,
                        file_name=widget.filename,
                    )
                widget.value = ""
                break
        else:
            return  # no message entered across all widgets

        message = ChatEntry(
            value=value, user=self.user, avatar=self.avatar
        )
        self.value.send(message=message)