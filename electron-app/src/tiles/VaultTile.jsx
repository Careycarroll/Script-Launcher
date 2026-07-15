import TileWithFallback from "./TileWithFallback";
import VaultDomain from "./VaultDomain";

export default function VaultTile() {
  return (
    <TileWithFallback
      domain="vault"
      title="Vault"
      componentName="Vault Domain"
      BespokeComponent={VaultDomain}
    />
  );
}
