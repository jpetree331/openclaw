import type { OpenClawPluginApi } from "../../src/plugins/types.js";
import { createDrivePlaygroundTools } from "./src/drive-playground-tool.js";

export default function register(api: OpenClawPluginApi) {
  const tools = createDrivePlaygroundTools(api);
  for (const tool of tools) {
    api.registerTool(tool, { optional: true });
  }
}
