"""
Module that holds the entry point for the console.
"""

import sys
import json
import signal
import logging
import cProfile
import pstats

from spotdl.console.download import download
from spotdl.console.preload import preload
from spotdl.console.sync import sync
from spotdl.console.save import save
from spotdl.download import Downloader
from spotdl.utils.config import DEFAULT_CONFIG, ConfigError, get_config
from spotdl.utils.ffmpeg import FFmpegError, download_ffmpeg, is_ffmpeg_installed
from spotdl.utils.config import get_config_file
from spotdl.utils.github import check_for_updates
from spotdl.utils.arguments import parse_arguments
from spotdl.utils.spotify import SpotifyClient, SpotifyError
from spotdl.download.downloader import DownloaderError


OPEARTIONS = {
    "download": download,
    "preload": preload,
    "sync": sync,
    "save": save,
}


def entry_point():
    """
    Console entry point for spotdl. This is where the magic happens.
    """

    # Don't log too much
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("spotipy").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    if getattr(sys, "frozen", False) and len(sys.argv) == 1:
        # If the application is frozen, we check for ffmpeg
        # if it's not present download it create config file
        if is_ffmpeg_installed() is False:
            download_ffmpeg()

        try:
            get_config()
        except ConfigError:
            config_path = get_config_file()
            with open(config_path, "w", encoding="utf-8") as config_file:
                json.dump(DEFAULT_CONFIG, config_file, indent=4)

    # Download ffmpeg if the `--download-ffmpeg` flag is passed
    # This is done before the argument parser so it doesn't require `operation`
    # and `query` to be passed. Exit after downloading ffmpeg
    if "--download-ffmpeg" in sys.argv:
        download_ffmpeg()

        return None

    # Generate the config file if it doesn't exist
    # or overwrite the current config file if the `--overwrite-config` flag is passed
    # This is done before the argument parser so it doesn't requires `operation`
    # and `query` to be passed. exit after downloading ffmpeg
    if "--generate-config" in sys.argv:
        config_path = get_config_file()
        with open(config_path, "w", encoding="utf-8") as config_file:
            json.dump(DEFAULT_CONFIG, config_file, indent=4)

        return None

    # Get information about the current version and display it
    # Exit after displaying the version
    if "--check-for-updates" in sys.argv:
        check_for_updates()

        return None

    # Parse the arguments
    arguments = parse_arguments()

    # Get the config file
    # It will automatically load if the `load_config` is set to True
    # in the config file
    config = {}
    if arguments.config or (
        get_config_file().exists() and get_config().get("load_config")
    ):
        config = get_config()

    # Create settings dict
    # Settings from config file will override the ones from the command line
    settings = {}
    for key in DEFAULT_CONFIG:
        if config.get(key) is None:
            # If the key is not in the arguments dict, use the default value
            settings[key] = arguments.__dict__.get(key) or DEFAULT_CONFIG[key]
        else:
            settings[key] = config[key]

    # Check if ffmpeg is installed
    if is_ffmpeg_installed() is False:
        raise FFmpegError(
            "FFmpeg is not installed. Please run `spotdl --download-ffmpeg` to install it, "
            "or `spotdl --ffmpeg /path/to/ffmpeg` to specify the path to ffmpeg."
        )

    # Initialize spotify client
    SpotifyClient.init(
        client_id=settings["client_id"],
        client_secret=settings["client_secret"],
        user_auth=settings["user_auth"],
        cache_path=settings["cache_path"],
        no_cache=settings["no_cache"],
        open_browser=not settings["headless"],
    )

    # If the application is frozen start web ui
    # or if the operation is `web`
    if (
        getattr(sys, "frozen", False)
        and len(sys.argv) == 1
        or arguments.operation == "web"
    ):
        from spotdl.console.web import (  # pylint: disable=C0415,C0410,W0707,W0611
            web,
        )

        # Don't log too much when running web ui & default logging argument
        if arguments.__dict__.get("log_level") is None:
            settings["log_level"] = "CRITICAL"

        # Start web ui
        web(settings)

        return None

    # Check if save file is present and if it's valid
    if isinstance(settings["save_file"], str) and not settings["save_file"].endswith(
        ".spotdl"
    ):
        raise DownloaderError("Save file has to end with .spotdl")

    if arguments.query and "saved" in arguments.query and not settings["user_auth"]:
        raise SpotifyError("You must be logged in to use the saved query.")

    # Initialize the downloader
    # for download, load and preload operations
    downloader = Downloader(
        audio_providers=settings["audio_providers"],
        lyrics_providers=settings["lyrics_providers"],
        ffmpeg=settings["ffmpeg"],
        bitrate=settings["bitrate"],
        ffmpeg_args=settings["ffmpeg_args"],
        output_format=settings["format"],
        save_file=settings["save_file"],
        threads=settings["threads"],
        output=settings["output"],
        overwrite=settings["overwrite"],
        search_query=settings["search_query"],
        cookie_file=settings["cookie_file"],
        log_level=settings["log_level"],
        simple_tui=settings["simple_tui"],
        restrict=settings["restrict"],
        print_errors=settings["print_errors"],
        sponsor_block=settings["sponsor_block"],
    )

    def graceful_exit(_signal, _frame):
        downloader.progress_handler.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, graceful_exit)
    signal.signal(signal.SIGTERM, graceful_exit)

    # Pick the operation to perform
    # based on the name and run it!
    OPEARTIONS[arguments.operation](
        query=arguments.query,
        save_path=settings["save_file"],
        downloader=downloader,
        m3u_file=settings["m3u"],
    )

    downloader.progress_handler.close()

    return None


def console_entry_point():
    """
    Wrapper around `entry_point` so we can profile the code
    """

    if "--profile" in sys.argv:
        with cProfile.Profile() as profile:
            entry_point()

        stats = pstats.Stats(profile)
        stats.sort_stats(pstats.SortKey.TIME)

        # Use snakeviz to visualize the profile
        stats.dump_stats("spotdl.profile")
    else:
        entry_point()
