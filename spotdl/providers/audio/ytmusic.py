"""
YTMusic module for downloading and searching songs.
"""

from typing import Any, Dict, List, Optional

from ytmusicapi import YTMusic
from slugify import slugify

from spotdl.utils.providers import match_percentage
from spotdl.providers.audio.base import AudioProvider, AudioProviderError
from spotdl.types import Song
from spotdl.utils.formatter import (
    create_song_title,
    parse_duration,
    create_search_query,
)


class YouTubeMusic(AudioProvider):
    """
    YouTube Music audio provider class
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """
        Initialize the YouTube Music API

        ### Arguments
        - args: Arguments passed to the `AudioProvider` class.
        - kwargs: Keyword arguments passed to the `AudioProvider` class.
        """

        super().__init__(*args, **kwargs)
        self.client = YTMusic()

        # Check if we are getting results from YouTube Music
        test_results = self.get_results("a")
        if len(test_results) == 0:
            raise AudioProviderError(
                "Could not connect to YouTube Music API. Use VPN or other audio provider."
            )

    def search(self, song: Song) -> Optional[str]:
        """
        Search for a song on YouTube Music.

        ### Arguments
        - song: The song to search for.

        ### Returns
        - The url of the best match or None if no match was found.
        """

        if self.search_query:
            search_query = create_search_query(
                song, self.search_query, False, None, True
            )
        else:
            # search for song using isrc if it's available
            if song.isrc:
                isrc_results = self.get_results(song.isrc, filter="songs")

                if len(isrc_results) == 1:
                    isrc_result = isrc_results[0]

                    name_match = match_percentage(
                        isrc_result["name"].lower(), song.name.lower()
                    )

                    delta = isrc_result["duration"] - song.duration
                    non_match_value = (delta**2) / song.duration * 100

                    time_match = 100 - non_match_value

                    if (
                        isrc_result
                        and isrc_result.get("link")
                        and name_match > 90
                        and time_match > 90
                    ):
                        return isrc_result["link"]

            search_query = create_song_title(song.name, song.artists).lower()

        # Query YTM by songs only first, this way if we get correct result on the first try
        # we don't have to make another request
        song_results = self.get_results(search_query, filter="songs")

        if self.filter_results:
            # Order results
            songs = self.order_results(song_results, song)
        else:
            songs = {}
            if len(song_results) > 0:
                songs = {song_results[0]["link"]: 100}

        # song type results are always more accurate than video type,
        # so if we get score of 80 or above
        # we are almost 100% sure that this is the correct link
        if len(songs) != 0:
            # get the result with highest score
            best_result = max(songs, key=lambda k: songs[k])

            if songs[best_result] >= 80:
                return best_result

        # We didn't find the correct song on the first try so now we get video type results
        # add them to song_results, and get the result with highest score
        video_results = self.get_results(search_query, filter="videos")

        if self.filter_results:
            # Order video results
            videos = self.order_results(video_results, song)
        else:
            videos = {}
            if len(video_results) > 0:
                videos = {video_results[0]["link"]: 100}

        # Merge songs and video results
        results = {**songs, **videos}

        # No matches found
        if not results:
            return None

        result_items = list(results.items())

        # Sort results by highest score
        sorted_results = sorted(result_items, key=lambda x: x[1], reverse=True)

        # Get the result with highest score
        # and return the link
        return sorted_results[0][0]

    def get_results(self, search_term: str, **kwargs) -> List[Dict[str, Any]]:
        """
        Get results from YouTube Music API and simplify them

        ### Arguments
        - search_term: The search term to search for.
        - kwargs: other keyword arguments passed to the `YTMusic.search` method.

        ### Returns
        - A list of simplified results (dicts)
        """

        results = self.client.search(search_term, **kwargs)

        # Simplify results
        simplified_results = []
        for result in results:
            if result.get("videoId") is None:
                continue

            simplified_results.append(
                {
                    "name": result["title"],
                    "type": result["resultType"],
                    "link": f"https://youtube.com/watch?v={result['videoId']}",
                    "album": result.get("album", {}).get("name"),
                    "duration": parse_duration(result.get("duration")),
                    "artists": ", ".join(map(lambda a: a["name"], result["artists"])),
                }
            )

        return simplified_results

    def order_results(
        self, results: List[Dict[str, Any]], song: Song
    ) -> Dict[str, Any]:
        """
        Filter results based on the song's metadata.

        ### Arguments
        - results: The results to filter.
        - song: The song to filter by.

        ### Returns
        - A dict of filtered results.
        """

        # Slugify some variables
        slug_song_name = slugify(song.name)
        slug_album_name = slugify(song.album_name)
        slug_song_artist = slugify(song.artist)
        slug_song_title = slugify(
            create_song_title(song.name, song.artists)
            if not self.search_query
            else create_search_query(song, self.search_query, False, None, True)
        )

        # Assign an overall avg match value to each result
        links_with_match_value = {}
        for result in results:
            # Slugify result title
            slug_result_name = slugify(result["name"])

            # check for common words in result name
            sentence_words = slug_song_name.replace("-", " ").split(" ")
            common_word = any(
                word != "" and word in slug_result_name for word in sentence_words
            )

            # skip results that have no common words in their name
            if not common_word:
                continue

            # Artist divide number
            artist_divide_number = len(song.artists)

            # Find artist match
            artist_match_number = 0.0
            if result["type"] == "song":
                # Artist results has only one artist
                # So we fallback to matching the song title
                # if len(result["artists"].split(",")) == 1:
                #     for artist in song.artists:
                #         artist_match_number += match_percentage(
                #             slugify(artist), slug_result_name
                #         )
                # else:
                #     for artist in song.artists:
                #         artist_match_number += match_percentage(
                #             slugify(artist), slugify(result["artists"])
                #         )

                for artist in song.artists:
                    artist_match_number += match_percentage(
                        slugify(artist), slugify(result["artists"])
                    )
            else:
                for artist in song.artists:
                    artist_match_number += match_percentage(
                        slugify(artist), slug_result_name
                    )

                # If we didn't find any artist match,
                # we fallback to channel name match
                if artist_match_number <= 50:
                    channel_name_match = match_percentage(
                        slugify(song.artist),
                        slugify(result["artists"]),
                    )
                    if channel_name_match > artist_match_number:
                        artist_match_number = channel_name_match
                        artist_divide_number = 1

            # skip results with artist match lower than 70%
            artist_match = artist_match_number / artist_divide_number
            if artist_match < 70:
                continue

            # Calculate name match
            # for different result types
            if result["type"] == "song":
                name_match = match_percentage(slug_result_name, slug_song_name)
            else:
                # We are almost certain that this result
                # contains the correct song artist
                # so if the title doesn't contain the song artist in it
                # we append slug_song_artist to the title
                if artist_match > 90 and slug_song_artist not in slug_result_name:
                    name_match = match_percentage(
                        f"{slug_song_artist}-{slug_result_name}", slug_song_title
                    )
                else:
                    name_match = match_percentage(slug_result_name, slug_song_title)

            # Drop results with name match lower than 50%
            if name_match < 50:
                continue

            # Find album match
            album_match = 0.0
            album = None

            # Calculate album match only for songs
            if result["type"] == "song":
                album = result.get("album")
                if album:
                    album_match = match_percentage(slugify(album), slug_album_name)

            # Calculate time match
            delta = result["duration"] - song.duration
            non_match_value = (delta**2) / song.duration * 100

            time_match = 100 - non_match_value

            if result["type"] == "song":
                if album is None:
                    # Don't use album match
                    # If we didn't find album for the result,
                    average_match = (artist_match + name_match + time_match) / 3
                elif (
                    match_percentage(album.lower(), result["name"].lower()) > 95
                    and album.lower() != song.album_name.lower()
                ):
                    # If the album name is similar to the result song name,
                    # But the album name is different from the song album name
                    # We don't use album match
                    average_match = (artist_match + name_match + time_match) / 3
                else:
                    average_match = (
                        artist_match + album_match + name_match + time_match
                    ) / 4
            else:
                # Don't use album match for videos
                average_match = (artist_match + name_match + time_match) / 3

            # the results along with the avg Match
            links_with_match_value[result["link"]] = average_match

        return links_with_match_value
