
import openmct from "openmct";
import COSGCPlugin from "./plugins/cosgc-plugin.js";

// Initialize Open MCT
openmct.setAssetPath("/openmct-assets");

// Standard Open MCT plugins
openmct.install(openmct.plugins.LocalStorage());
openmct.install(openmct.plugins.MyItems());
openmct.install(openmct.plugins.UTCTimeSystem());

// Show the last 15 minutes of telemetry
openmct.time.setClock("local");
openmct.time.setClockOffsets({
    start: -15 * 60 * 1000,
    end: 0
});
openmct.time.setTimeSystem("utc");

// Install our custom COSGC functionality
openmct.install(COSGCPlugin());

// Start the application
openmct.start();
