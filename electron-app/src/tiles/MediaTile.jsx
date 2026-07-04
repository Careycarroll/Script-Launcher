import TileWithFallback from "./TileWithFallback";
import PanoptoDownloader from "./PanoptoDownloader";

export default function MediaTile() {
  return (
    <TileWithFallback
      domain="media"
      title="Media"
      componentName="Panopto Downloader"
      BespokeComponent={PanoptoDownloader}
    />
  );
}
