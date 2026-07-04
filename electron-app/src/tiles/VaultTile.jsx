import TileWithFallback from "./TileWithFallback";
import VaultWorkbench from "./VaultWorkbench";

export default function VaultTile() {
  return (
    <TileWithFallback
      domain="vault"
      title="Vault"
      componentName="Vault Workbench"
      BespokeComponent={VaultWorkbench}
    />
  );
}
