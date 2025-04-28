from pathlib import Path
from glob import iglob

from librespot.metadata import (
    AlbumId,
    ArtistId,
    PlaylistId,
    ShowId,
)

from zotify import ApiClient, API_MAX_REQUEST_LIMIT
from zotify.config import Config
from zotify.file import LocalFile
from zotify.utils import (
    MetadataEntry,
    PlayableData,
    PlayableType,
    bytes_to_base62,
    fix_filename,
)


class Collection:
    def __init__(self, api: ApiClient):
        self.playables: list[PlayableData] = []
        self.path: Path = None
        self.api = api
        self.offset = 0

    def set_path(self):
        if len(self.playables) == 0:
            raise IndexError("Collection is empty!")

        meta_tags = ["album_artist", "album", "podcast", "playlist"]
        library = Path(self.playables[0].library)
        output = self.playables[0].output_template
        metadata = self.playables[0].metadata

        for meta in metadata:
            if meta.name in meta_tags:
                output = output.replace(
                    "{" + meta.name + "}", fix_filename(meta.string)
                )

        if type(self) is Track or type(self) is Episode:
            self.path = library
        else:
            self.path = library.joinpath(output).expanduser().parent

    def get_existing(self, ext: str) -> dict[str, str]:
        existing: dict[str, str] = {}

        if self.path is None:
            self.set_path()
        if self.path.exists():
            if type(self) is Track or type(self) is Episode:
                file_path = "**/*.{}".format(ext)
            else:
                file_path = "*.{}".format(ext)
            scan_path = str(self.path.joinpath(file_path))

            # Check contents of path
            for file in iglob(scan_path, recursive=True):
                f_path = Path(file)
                f = LocalFile(f_path)
                try:
                    existing[f.get_metadata("spotid")] = f_path.stem
                except IndexError:
                    pass

            for playable in self.playables:
                if playable.id in existing.keys():
                    playable.existing = True

        return existing

    def get_duplicates(
        self, ext: str, album_lib: Path, playlist_lib: Path, podcast_lib: Path
    ) -> dict[str, str]:
        existing: dict[str, str] = {}
        duplicates: dict[str, str] = {}
        scan_paths = []

        if self.path is None:
            self.set_path()
        if self.path.exists():
            file_path = "*.{}".format(ext)
            collection_path = str(self.path.joinpath(file_path))

        file_path = "**/*.{}".format(ext)
        # Scan album library path
        scan_paths.append(str(album_lib.joinpath(file_path)))
        # Scan playlist library path
        scan_paths.append(str(playlist_lib.joinpath(file_path)))
        # Scan podcast library path
        scan_paths.append(str(podcast_lib.joinpath(file_path)))

        for scan_path in scan_paths:
            for file in iglob(scan_path, recursive=True):
                f_path = Path(file)
                if self.path.exists() and f_path.match(collection_path):
                    continue
                f = LocalFile(f_path)
                try:
                    existing[f.get_metadata("spotid")] = f_path.stem
                except IndexError:
                    pass

            for playable in self.playables:
                if playable.id in existing.keys():
                    playable.duplicate = True
                    duplicates[playable.id] = existing[playable.id]

            existing = {}

        return duplicates

    def get_metadata(self):
        params = {}
        ids = ""
        offset_start = self.offset

        for playable in self.playables[self.offset :]:
            if (
                self.offset == offset_start
                or (self.offset % API_MAX_REQUEST_LIMIT) != 0
            ):
                ids = f"{ids},{playable.id}"
                self.offset += 1
            else:
                break

        metadata = []
        params = {"ids": ids.strip(",")}
        if isinstance(self, (Album, Artist, Playlist, Track)):
            r = self.api.invoke_url(
                "tracks", params, limit=API_MAX_REQUEST_LIMIT, offset=offset_start
            )

            for track in r["tracks"]:
                # Get title, artist, and id
                track_metadata = [
                    MetadataEntry("spotid", track["id"]),
                    MetadataEntry("title", track["name"]),
                    MetadataEntry("artists", [a["name"] for a in track["artists"]]),
                ]
                metadata.append(track_metadata)
        else:
            r = self.api.invoke_url(
                "episodes", params, limit=API_MAX_REQUEST_LIMIT, offset=offset_start
            )

            for episode in r["episodes"]:
                # Get title and id
                episode_metadata = [
                    MetadataEntry("spotid", episode["id"]),
                    MetadataEntry("title", episode["name"]),
                ]
                metadata.append(episode_metadata)

        return metadata

    def get_match(self):
        count = 0

        # Output format of existing tracks must match
        # with the current download command
        if self.path is None:
            self.set_path()
        if self.path.exists():
            for playable in self.playables:
                if count == self.offset:
                    # Get new batch of metadata
                    metadata = self.get_metadata()

                # Create file path, include all extensions
                filename = Path(self.playables[0].output_template).name
                filename = filename.replace("{episode_number}", "*")
                filename = filename.replace("{track_number}", "*")
                for meta in metadata[count % API_MAX_REQUEST_LIMIT]:
                    filename = filename.replace(
                        "{" + meta.name + "}", fix_filename(meta.string)
                    )
                scan_path = f"{self.path.joinpath(filename)}.*"

                for file in iglob(scan_path):
                    f = LocalFile(Path(file))
                    f.write_metadata(metadata[count % API_MAX_REQUEST_LIMIT])

                count += 1


class Album(Collection):
    def __init__(self, b62_id: str, api: ApiClient, config: Config = Config()):
        super().__init__(api)
        album = api.get_metadata_4_album(AlbumId.from_base62(b62_id))
        total_discs = len(album.disc)
        for disc in album.disc:
            for track in disc.track:
                metadata = [
                    MetadataEntry("spotid", bytes_to_base62(track.gid)),
                    MetadataEntry("album_artist", album.artist[0].name),
                    MetadataEntry("album", album.name),
                    MetadataEntry("discnumber", disc.number),
                    MetadataEntry("disctotal", total_discs),
                ]
                self.playables.append(
                    PlayableData(
                        PlayableType.TRACK,
                        bytes_to_base62(track.gid),
                        config.album_library,
                        config.output_album,
                        metadata,
                    )
                )


class Artist(Collection):
    def __init__(self, b62_id: str, api: ApiClient, config: Config = Config()):
        super().__init__(api)
        artist = api.get_metadata_4_artist(ArtistId.from_base62(b62_id))
        
        # Process all content types: albums, singles, compilations, and appearances
        all_groups = []
        if artist.album_group:
            all_groups.extend(artist.album_group)
        if artist.single_group:
            all_groups.extend(artist.single_group)
        if artist.compilation_group:
            all_groups.extend(artist.compilation_group)
        if artist.appears_on_group:
            all_groups.extend(artist.appears_on_group)
            
        for album_group in all_groups:
            try:
                album = api.get_metadata_4_album(
                    AlbumId.from_base62(bytes_to_base62(album_group.album[0].gid))
                )
                total_discs = len(album.disc)
                for disc in album.disc:
                    for track in disc.track:
                        metadata = [
                            MetadataEntry("spotid", bytes_to_base62(track.gid)),
                            MetadataEntry("album_artist", album.artist[0].name),
                            MetadataEntry("album", album.name),
                            MetadataEntry("discnumber", disc.number),
                            MetadataEntry("disctotal", total_discs),
                        ]
                        self.playables.append(
                            PlayableData(
                                PlayableType.TRACK,
                                bytes_to_base62(track.gid),
                                config.album_library,
                                config.output_album,
                                metadata,
                            )
                        )
            except Exception as e:
                # Skip albums that can't be processed
                print(f"Error processing album: {e}")
                continue


class Show(Collection):
    def __init__(self, b62_id: str, api: ApiClient, config: Config = Config()):
        super().__init__(api)
        show = api.get_metadata_4_show(ShowId.from_base62(b62_id))
        for episode in show.episode:
            metadata = [
                MetadataEntry("spotid", bytes_to_base62(episode.gid)),
                MetadataEntry("podcast", show.name),
            ]
            self.playables.append(
                PlayableData(
                    PlayableType.EPISODE,
                    bytes_to_base62(episode.gid),
                    config.podcast_library,
                    config.output_podcast,
                    metadata,
                )
            )


class Playlist(Collection):
    def __init__(self, b62_id: str, api: ApiClient, config: Config = Config()):
        super().__init__(api)
        playlist = api.get_playlist(PlaylistId(b62_id))
        for i in range(len(playlist.contents.items)):
            item = playlist.contents.items[i]
            split = item.uri.split(":")
            playable_type = split[1]
            playable_id = split[2]
            metadata = [
                MetadataEntry("spotid", playable_id),
                MetadataEntry("playlist", playlist.attributes.name),
                MetadataEntry("playlist_length", playlist.length),
                MetadataEntry("playlist_owner", playlist.owner_username),
                MetadataEntry(
                    "playlist_number",
                    i + 1,
                    str(i + 1).zfill(len(str(playlist.length + 1))),
                ),
            ]
            if playable_type == "track":
                self.playables.append(
                    PlayableData(
                        PlayableType.TRACK,
                        playable_id,
                        config.playlist_library,
                        config.output_playlist_track,
                        metadata,
                    )
                )
            elif playable_type == "episode":
                self.playables.append(
                    PlayableData(
                        PlayableType.EPISODE,
                        playable_id,
                        config.playlist_library,
                        config.output_playlist_episode,
                        metadata,
                    )
                )
            elif playable_type == "local":
                # Ignore local files
                pass
            else:
                raise ValueError("Unknown playable content", playable_type)


class Track(Collection):
    def __init__(self, b62_id: str, api: ApiClient, config: Config = Config()):
        super().__init__(api)
        metadata = [MetadataEntry("spotid", b62_id)]
        self.playables.append(
            PlayableData(
                PlayableType.TRACK,
                b62_id,
                config.album_library,
                config.output_album,
                metadata,
            )
        )


class Episode(Collection):
    def __init__(self, b62_id: str, api: ApiClient, config: Config = Config()):
        super().__init__(api)
        metadata = [MetadataEntry("spotid", b62_id)]
        self.playables.append(
            PlayableData(
                PlayableType.EPISODE,
                b62_id,
                config.podcast_library,
                config.output_podcast,
                metadata,
            )
        )
