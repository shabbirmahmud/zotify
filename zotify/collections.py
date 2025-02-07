from pathlib import Path
from glob import iglob

from librespot.metadata import (
    AlbumId,
    ArtistId,
    PlaylistId,
    ShowId,
)

from zotify import ApiClient
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
    def __init__(self):
        self.playables: list[PlayableData] = []
    
    def get_existing(self, ext: str) -> dict[str, str]:
        existing: dict[str, str] = {}

        meta_tags = ["album_artist", "album", "podcast", "playlist"]
        library = Path(self.playables[0].library)
        output = self.playables[0].output_template
        metadata = self.playables[0].metadata
        id_type = self.playables[0].type
        
        for meta in metadata:
            if meta.name in meta_tags:
                output = output.replace(
                    "{" + meta.name + "}", fix_filename(meta.string)
                )
        
        collection_path = library.joinpath(output).expanduser()
        if collection_path.parent.exists():
            file_path = "*.{}".format(ext)
            scan_path = str(collection_path.parent.joinpath(file_path))

            # Check contents of path
            for file in iglob(scan_path):
                f_path = Path(file)
                f = LocalFile(f_path)
                existing[f.get_metadata("key")] = f_path.stem
        
            for playable in self.playables:
                if playable.id in existing.keys():
                    playable.existing = True
        
        return existing


class Album(Collection):
    def __init__(self, b62_id: str, api: ApiClient, config: Config = Config()):
        super().__init__()
        album = api.get_metadata_4_album(AlbumId.from_base62(b62_id))
        for disc in album.disc:
            for track in disc.track:
                metadata = [MetadataEntry("key", bytes_to_base62(track.gid))]
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
        super().__init__()
        artist = api.get_metadata_4_artist(ArtistId.from_base62(b62_id))
        for album_group in (
            artist.album_group
            and artist.single_group
            and artist.compilation_group
            and artist.appears_on_group
        ):
            album = api.get_metadata_4_album(AlbumId.from_hex(album_group.album[0].gid))
            for disc in album.disc:
                for track in disc.track:
                    metadata = [MetadataEntry("key", bytes_to_base62(track.gid))]
                    self.playables.append(
                        PlayableData(
                            PlayableType.TRACK,
                            bytes_to_base62(track.gid),
                            config.album_library,
                            config.output_album,
                            metadata,
                        )
                    )


class Show(Collection):
    def __init__(self, b62_id: str, api: ApiClient, config: Config = Config()):
        super().__init__()
        show = api.get_metadata_4_show(ShowId.from_base62(b62_id))
        for episode in show.episode:
            metadata = [MetadataEntry("key", bytes_to_base62(episode.gid))]
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
        super().__init__()
        playlist = api.get_playlist(PlaylistId(b62_id))
        for i in range(len(playlist.contents.items)):
            item = playlist.contents.items[i]
            split = item.uri.split(":")
            playable_type = split[1]
            playable_id = split[2]
            metadata = [
                MetadataEntry("key", playable_id),
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
        super().__init__()
        metadata = [MetadataEntry("key", b62_id)]
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
        super().__init__()
        metadata = [MetadataEntry("key", b62_id)]
        self.playables.append(
            PlayableData(
                PlayableType.EPISODE,
                b62_id,
                config.podcast_library,
                config.output_podcast,
                metadata,
            )
        )
