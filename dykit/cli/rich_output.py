from __future__ import annotations

from rich.console import Console

console = Console()
stderr_console = Console(stderr=True)


def out(text: str) -> None:
    console.print(text)


def err(text: str) -> None:
    stderr_console.print(text, style="bold red")


def style_message(content: str, msg_type: str) -> str:
    if msg_type == "uenter":
        return f"[dim]{content}[/dim]"
    if msg_type == "dgb":
        return f"[black on yellow]{content}[/black on yellow]"
    if msg_type in {"anbc", "rnewbc"}:
        return f"[black on cyan]{content}[/black on cyan]"
    if msg_type in {"blab", "upgrade"}:
        return f"[black on magenta]{content}[/black on magenta]"
    return content
