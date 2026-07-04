import { Component } from "react";
import RegistryTile from "../RegistryTile";

// Error boundary + fallback wrapper. If the bespoke component throws
// on render or mount, RegistryTile is shown instead with a banner
// explaining what happened. User can retry or expand the error.
class TileWithFallback extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null, showDetails: false };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error(
      `[TileWithFallback:${this.props.componentName}]`,
      error,
      info,
    );
  }

  retry = () => this.setState({ error: null, showDetails: false });

  render() {
    const { error, showDetails } = this.state;
    const { domain, title, componentName, BespokeComponent } = this.props;

    if (error) {
      return (
        <div className="tile-fallback">
          <div className="tile-fallback-banner">
            <div className="tile-fallback-message">
              <strong>{componentName} encountered an error</strong> — showing
              basic {title} view.
            </div>
            <div className="tile-fallback-actions">
              <button
                className="btn-secondary"
                onClick={() =>
                  this.setState((s) => ({ showDetails: !s.showDetails }))
                }
              >
                {showDetails ? "Hide details" : "Show details"}
              </button>
              <button className="btn-secondary" onClick={this.retry}>
                Retry
              </button>
            </div>
          </div>
          {showDetails && (
            <pre className="tile-fallback-details">
              {error?.stack || error?.message || String(error)}
            </pre>
          )}
          <RegistryTile domain={domain} title={title} />
        </div>
      );
    }

    if (!BespokeComponent) {
      return <RegistryTile domain={domain} title={title} />;
    }

    return <BespokeComponent domain={domain} title={title} />;
  }
}

export default TileWithFallback;
