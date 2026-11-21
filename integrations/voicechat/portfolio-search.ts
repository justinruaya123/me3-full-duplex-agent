// This project worker exposes only the pinned plugin's Brave search tool.
import {resolveConfig} from "./node_modules/@arcanemachine/pi-web-search/src/config.ts";
import {createSearchToolController} from "./node_modules/@arcanemachine/pi-web-search/src/tools/search-web.ts";
import type {ExtensionAPI} from "@earendil-works/pi-coding-agent";

export default function portfolioSearch(pi: ExtensionAPI) {
  const config = resolveConfig({}, {"pi-web-search":{backends:["brave"]}});
  let searched = false;
  createSearchToolController({
    registerTool(tool) {
      pi.registerTool({...tool, async execute(id, params, signal, update, ctx) {
        if (searched) throw Error("The portfolio search has already run.");
        searched = true;
        return tool.execute(id, {...params, query:process.env.ME3_PORTFOLIO_QUERY!, limit:8}, signal, update, ctx);
      }});
    }
  } as ExtensionAPI, () => config).register();
  pi.on("before_provider_request", ({payload}) => {
    if (!Array.isArray(payload.tools)) return;
    if (searched) return {...payload,tools:[]};
    if (payload.tools.some(tool => tool.function?.name === "search_web"))
      return {...payload,tool_choice:{type:"function",function:{name:"search_web"}}};
  });
}
