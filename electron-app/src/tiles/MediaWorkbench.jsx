import { useState } from "react";
import PanoptoDownloader from "./PanoptoDownloader";
import GenericYtdlpDownloader from "./GenericYtdlpDownloader";

const TOOLS = [
  { key: "panopto", label: "Panopto", component: PanoptoDownloader },
  { key: "generic", label: "Generic yt-dlp", component: GenericYtdlpDownloader },
];

export default function MediaWorkbench() {
  const [active, setActive] = useState("panopto");
  const ActiveComponent = TOOLS.find((t) => t.key === active)?.component || PanoptoDownloader;

  return (
    <div className="media-workbench">
      <div className="media-tool-tabs">
        {TOOLS.map((tool) => (
          <button
            key={tool.key}
            className={`media-tool-tab ${active === tool.key ? "active" : ""}`}
            onClick={() => setActive(tool.key)}
          >
            {tool.label}
          </button>
        ))}
      </div>
      <div className="media-tool-body">
        <ActiveComponent />
      </div>
    </div>
  );
}
