"""
Open Directory Scanner & Fzf.py
----

This is a highly powerful, smart and recursive
directory scanner for online resources. Paired
up with Fzf.py, it allows for clean and easy
selection of files.

    Author: github@justfoolingaround (KR)
    Version: 1.0.0

Automatically detects various resolutions for
same series and gives them during the final
return.
"""


import re
from collections import defaultdict
from urllib.parse import unquote

import anitopy
import click
import fzf
import requests
import yarl

__version__ = "1.0.0"


http_client = requests.Session()

http_client.headers.update(
    {
        "User-Agent": f"ODSFZF/{__version__}",
    }
)


URL_SCANNER_RE = re.compile(r'<a .*?href="(?!\?)(?P<child>.+?(?P<is_dir>/)?)">')
RELATIVE_TO_CURRENT_URL_RE = re.compile(r"(?:\.+?/)+")
SEASON_LISTING = re.compile(
    r"(?!^)(?:\b|\.+)"
    r"(?:(?:s(?:eason\s+)?)?"
    r"(?P<season>[0-9]+(?:\.[0-9]+)?))\s*"
    r"(?:[xe-]|\s+(?:ep(?:isode)?)?)\s*"
    r"(?P<episode>[0-9]+(?:\.[0-9]+)?)"
    r"(?:\b|\.+)",
    flags=re.IGNORECASE | re.MULTILINE,
)

def get_season_listing_from_name(name):

    season_listing = SEASON_LISTING.search(name)

    if season_listing:
        name = SEASON_LISTING.sub("", name).strip()

    return name, *(
        season_listing.group("season", "episode") if season_listing else (None, None)
    )


def get_pseudo_float_string(string_source: float):
    return f"{int(string_source) if string_source.is_integer() else string_source:{'02d' if string_source.is_integer() else '02.0f'}}"


def safe_url_join(url: str, path: str):

    return url.removesuffix("/") + "/" + path.removeprefix("/")



def iterate_file_system(session: requests.Session, url, *, parent=None):

    url = yarl.URL(url)
    is_subtitle_path = False

    if not url.host:

        is_subtitle_path = any(url.path.endswith(subtitle_path) for subtitle_path in ("Subs/", "Sub/"))

        if parent is None:
            raise ValueError("parent is required for relative URLs")
        else:
            parsed_parent = yarl.URL(parent)

            if parsed_parent.parent == url:
                return

            url = yarl.URL(safe_url_join(parsed_parent.human_repr(), url.human_repr()))

    with session.get(url.human_repr(), stream=True) as url_response:

        for line in url_response.iter_lines(decode_unicode=True):
            for site_url in URL_SCANNER_RE.finditer(line):

                href = site_url.group("child")
                is_dir = site_url.group("is_dir") is not None

                if RELATIVE_TO_CURRENT_URL_RE.match(href):
                    continue

                if is_dir:

                    iterator = iterate_file_system(session, href, parent=url.human_repr())

                    if is_subtitle_path:
                        yield {
                            "type": "subtitle",
                            "attrs": {
                                "subtitle_for": (parent.rsplit("/", 1) or (None,))[-1],
                                "subtitles": list(iterator),
                            },
                        }
                    else:
                        yield from iterator
                else:
                    yield {
                        "type": "file",
                        "attrs": anitopy.parse(href),
                        "origin": href,
                        "url": url.join(yarl.URL(href)).human_repr(),
                        "path": url.join(yarl.URL(href)).path,
                    }



def send_fs_to_fzf(genexp: iterate_file_system, *, show_path=False):

    subtitle_holder = defaultdict(list)
    resolution_holder = defaultdict(list)

    def to_fzf_prompt():
        for file in genexp:

            file_type = file["type"]

            if file_type == "subtitle":
                subtitle_holder[file["attrs"]["subtitle_for"]].append(file)

                continue

            if file_type == "file":
                has_subtitles = len(
                    subtitle_holder.get("origin", {})
                    .get("attrs", {})
                    .get("subtitles", [])
                )

                attributes = file["attrs"]

                if "anime_title" in attributes:
                    name = attributes["anime_title"]
                else:
                    name = attributes["file_name"]

                name = unquote(name)

                season_listing = None

                (
                    pseudo_name,
                    pseudo_season,
                    pseudo_episode,
                ) = get_season_listing_from_name(name)

                if "episode_number" in attributes:
                    pseudo_episode = float(attributes["episode_number"])
                else:
                    name = pseudo_name

                if "anime_season" in attributes:
                    pseudo_season = float(attributes["anime_season"])
                else:
                    name = pseudo_name

                if pseudo_episode is not None:
                    season_listing = get_pseudo_float_string(float(pseudo_episode))

                if pseudo_season is not None:
                    season_text = get_pseudo_float_string(float(pseudo_season))

                    if season_listing is None:
                        season_listing = f"{season_text}x0?"
                    else:
                        season_listing = f"{season_text}x{season_listing}"

                file["name"] = name = " ".join(
                    (name.strip(". ").replace(".", " "), season_listing or "")
                ).strip(". ")

                was_already_in = name in resolution_holder

                if "video_resolution" in attributes:
                    resolution_holder[name].append(file)

                if was_already_in:
                    continue

                yield (
                    name
                    + (" [subtitles]" if has_subtitles else "")
                    + (
                        f" [{attributes['file_extension']}]"
                        if "file_extension" in attributes
                        else ""
                    )
                    + (f" @ {file['path']!r}" if ("path" in file and show_path) else ""),
                    file,
                )

    _, file_ref = fzf.fzf_prompt(
        to_fzf_prompt(),
        processor=lambda component: component[0],
        height="50%",
        reverse_results=True,
        cycle=True,
        mouse=False,
        select_first=True,
    )

    resolutions = resolution_holder.get(file_ref["name"], [file_ref])

    subtitles = subtitle_holder.get(file_ref["origin"], [])

    if subtitles:
        for resolution in resolutions:
            resolution["subtitles"] = subtitles

    return resolutions


@click.command()
@click.version_option(__version__, "-v", "--version")
@click.argument("url")
@click.option("--hush-path", is_flag=True, help="Don't how path alongide listing.", default=False)
def odsfzf__main__(url, hush_path):
    """
    Open Directory Search FZF.
    """

    print(send_fs_to_fzf(iterate_file_system(http_client, url), show_path=not hush_path))


if __name__ == "__main__":
    odsfzf__main__()
