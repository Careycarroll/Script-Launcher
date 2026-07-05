import TileWithFallback from "./TileWithFallback";
import MediaWorkbench from "./MediaWorkbench";

export default function MediaTile() {
  return (
    <TileWithFallback
      domain="media"
      title="Media"
      componentName="Media Workbench"
      BespokeComponent={MediaWorkbench}
    />
  );
}
