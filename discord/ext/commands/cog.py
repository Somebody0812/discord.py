# -*- coding: utf-8 -*-

"""
The MIT License (MIT)

Copyright (c) 2015-2017 Rapptz

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
"""

import inspect
import copy
from ._types import _BaseCommand

__all__ = ('CogMeta', 'Cog')

class CogMeta(type):
    """A　metaclass for defining a cog.

    Note that you should probably not use this directly. It is exposed
    purely for documentation purposes along with making custom metaclasses to intermix
    with other metaclasses such as the :class:`abc.ABCMeta` metaclass.

    For example, to create an abstract cog mixin class, the following would be done.

    .. code-block:: python3

        import abc

        class CogABCMeta(commands.CogMeta, abc.ABCMeta):
            pass

        class SomeMixin(metaclass=abc.ABCMeta):
            pass

        class SomeCogMixin(SomeMixin, commands.Cog, metaclass=CogABCMeta):
            pass

    .. note::

        When passing an attribute of a metaclass that is documented below, note
        that you must pass it as a keyword-only argument to the class creation
        like the following example:

        .. code-block:: python3

            class MyCog(commands.Cog, name='My Cog'):
                pass

    Attributes
    -----------
    name: :class:`str`
        The cog name. By default, it is the name of the class with no modification.
    command_attrs: :class:`dict`
        A list of attributes to apply to every command inside this cog. The dictionary
        is passed into the :class:`Command` (or its subclass) options at ``__init__``.
        If you specify attributes inside the command attribute in the class, it will
        override the one specified inside this attribute. For example:

        .. code-block:: python3

            class MyCog(commands.Cog, command_attrs=dict(hidden=True)):
                @commands.command()
                async def foo(self, ctx):
                    pass # hidden -> True

                @commands.command(hidden=False)
                async def bar(self, ctx):
                    pass # hidden -> False
    """

    def __new__(cls, *args, **kwargs):
        name, bases, attrs = args
        attrs['__cog_name__'] = kwargs.pop('name', name)
        attrs['__cog_settings__'] = command_attrs = kwargs.pop('command_attrs', {})

        commands = []
        listeners = []

        for elem, value in attrs.items():
            if isinstance(value, _BaseCommand):
                commands.append(value)
            elif inspect.iscoroutinefunction(value):
                try:
                    is_listener = getattr(value, '__cog_listener__')
                except AttributeError:
                    continue
                else:
                    listeners.append((value.__cog_listener_name__, value.__name__))

        attrs['__cog_commands__'] = commands # this will be copied in Cog.__new__
        attrs['__cog_listeners__'] = tuple(listeners)
        return super().__new__(cls, name, bases, attrs, **kwargs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args)

    @classmethod
    def qualified_name(cls):
        return cls.__cog_name__

class Cog(metaclass=CogMeta):
    """The base class that all cogs must inherit from.

    A cog is a collection of commands, listeners, and optional state to
    help group commands together. More information on them can be found on
    the :ref:`ext_commands_cogs` page.

    When inheriting from this class, the options shown in :class:`CogMeta`
    are equally valid here.
    """

    def __new__(cls, *args, **kwargs):
        # For issue 426, we need to store a copy of the command objects
        # since we modify them to inject `self` to them.
        # To do this, we need to interfere with the Cog creation process.
        self = super().__new__(cls)
        cmd_attrs = cls.__cog_settings__

        # Either update the command with the cog provided defaults or copy it.
        self.__cog_commands__ = tuple(c._update_copy(cmd_attrs) for c in cls.__cog_commands__)

        lookup = {
            cmd.qualified_name: cmd
            for cmd in self.__cog_commands__
        }

        # Update the Command instances dynamically as well
        for command in self.__cog_commands__:
            setattr(self, command.callback.__name__, command)
            parent = command.parent
            if parent is not None:
                # Get the latest parent reference
                parent = lookup[parent.qualified_name]

                # Update our parent's reference to ourself
                removed = parent.remove_command(command.name)
                parent.add_command(command)

        return self

    def get_commands(self):
        r"""Returns a :class:`tuple` of :class:`.Command`\s and its subclasses that are
        defined inside this cog.
        """
        return self.__cog_commands__

    def walk_commands(self):
        """An iterator that recursively walks through this cog's commands and subcommands."""
        from .core import GroupMixin
        for command in self.__cog_commands__:
            yield command
            if isinstance(command, GroupMixin):
                yield from command.walk_commands()

    def get_listeners(self):
        """Returns a :class:`list` of (name, function) listener pairs that are defined in this cog."""
        return [(name, getattr(self, method_name)) for name, method_name in self.__cog_listeners__]

    @classmethod
    def _get_overridden_method(cls, method):
        """Return None if the method is not overridden. Otherwise returns the overridden method."""
        if method.__func__ is getattr(cls, method.__name__):
            return None
        return method

    @classmethod
    def listener(cls, name=None):
        """A decorator that marks a function as a listener.

        This is the cog equivalent of :meth:`.Bot.listen`.

        Parameters
        ------------
        name: :class:`str`
            The name of the event being listened to. If not provided, it
            defaults to the function's name.

        Raises
        --------
        TypeError
            The function is not a coroutine function.
        """

        def decorator(func):
            if not inspect.iscoroutinefunction(func):
                raise TypeError('Listener function must be a coroutine function.')
            func.__cog_listener__ = True
            func.__cog_listener_name__ = name or func.__name__
            return func
        return decorator

    def cog_unload(self):
        """A special method that is called when the cog gets removed.

        This function **cannot** be a coroutine. It must be a regular
        function.

        Subclasses must replace this if they want special unloading behaviour.
        """
        pass

    def bot_check_once(self, ctx):
        """A special method that registers as a :meth:`.Bot.check_once`
        check.

        This function **can** be a coroutine and must take a sole parameter,
        ``ctx``, to represent the :class:`.Context`.
        """
        return True

    def bot_check(self, ctx):
        """A special method that registers as a :meth:`.Bot.check`
        check.

        This function **can** be a coroutine and must take a sole parameter,
        ``ctx``, to represent the :class:`.Context`.
        """
        return True

    def cog_check(self, ctx):
        """A special method that registers as a :func:`commands.check`
        for every command and subcommand in this cog.

        This function **can** be a coroutine and must take a sole parameter,
        ``ctx``, to represent the :class:`.Context`.
        """
        return True

    def cog_command_error(self, ctx, error):
        """A special method that is called whenever an error
        is dispatched inside this cog.

        This is similar to :func:`.on_command_error` except only applying
        to the commands inside this cog.

        This function **can** be a coroutine.

        Parameters
        -----------
        ctx: :class:`.Context`
            The invocation context where the error happened.
        error: :class:`CommandError`
            The error that happened.
        """
        pass

    async def cog_before_invoke(self, ctx):
        """A special method that acts as a cog local pre-invoke hook.

        This is similar to :meth:`.Command.before_invoke`.

        This **must** be a coroutine.

        Parameters
        -----------
        ctx: :class:`.Context`
            The invocation context.
        """
        pass

    async def cog_after_invoke(self, ctx):
        """A special method that acts as a cog local post-invoke hook.

        This is similar to :meth:`.Command.after_invoke`.

        This **must** be a coroutine.

        Parameters
        -----------
        ctx: :class:`.Context`
            The invocation context.
        """
        pass

    def _inject(self, bot):
        cls = self.__class__

        # realistically, the only thing that can cause loading errors
        # is essentially just the command loading, which raises if there are
        # duplicates. When this condition is met, we want to undo all what
        # we've added so far for some form of atomic loading.
        for index, command in enumerate(self.__cog_commands__):
            command.cog = self
            if command.parent is None:
                try:
                    bot.add_command(command)
                except Exception as e:
                    # undo our additions
                    for to_undo in self.__cog_commands__[:index]:
                        bot.remove_command(to_undo)
                    raise e

        # check if we're overriding the default
        if cls.bot_check is not Cog.bot_check:
            bot.add_check(self.bot_check)

        if cls.bot_check_once is not Cog.bot_check_once:
            bot.add_check(self.bot_check_once, call_once=True)

        # while Bot.add_listener can raise if it's not a coroutine,
        # this precondition is already met by the listener decorator
        # already, thus this should never raise.
        # Outside of, memory errors and the like...
        for name, method_name in self.__cog_listeners__:
            bot.add_listener(getattr(self, method_name), name)

        return self

    def _eject(self, bot):
        cls = self.__class__

        try:
            for command in self.__cog_commands__:
                if command.parent is None:
                    bot.remove_command(command.name)

            for _, method_name in self.__cog_listeners__:
                bot.remove_listener(getattr(self, method_name))

            if cls.bot_check is not Cog.bot_check:
                bot.remove_check(self.bot_check)

            if cls.bot_check_once is not Cog.bot_check_once:
                bot.remove_check(self.bot_check_once, call_once=True)
        finally:
            self.cog_unload()