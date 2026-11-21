import {realpathSync, mkdirSync} from "node:fs";
import {resolve, join} from "node:path";
import {fileURLToPath} from "node:url";
import {ProjectTrustStore} from "@earendil-works/pi-coding-agent";

export function prepareTrust(root, profile, explicitlyTrust = false) {
  root = realpathSync(root);
  const store = new ProjectTrustStore(profile);
  const entry = store.getEntry(root);
  if (entry?.decision === false && !explicitlyTrust)
    throw Error("BMO's project profile has a saved denial. To trust this checkout, run bash integrations/voicechat/start.sh --trust-project.");
  if (entry?.path !== root || entry?.decision !== true) store.set(root,true);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const root = realpathSync(fileURLToPath(new URL("../..",import.meta.url)));
    const client = realpathSync(process.env.ME3_CLIENT_HOME);
    const profile = join(client,".local/pi");
    mkdirSync(profile,{recursive:true,mode:0o700});
    if (realpathSync(profile) !== profile || process.env.PI_CODING_AGENT_DIR !== profile)
      throw Error("BMO needs its own .local/pi directory inside the project.");
    prepareTrust(root,profile,process.argv.includes("--trust-project"));
    if (process.argv.includes("--sanity") || process.argv.includes("--trust-project"))
      console.log("Trusted checkout: " + root + "\nProject Pi profile: " + profile);
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
