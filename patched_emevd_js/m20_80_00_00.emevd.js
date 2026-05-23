// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90035010, 20800200, 20800210);
    $InitializeCommonEvent(0, 90035011, 20800601, 20801600, 20801610, 20801611, 20806200, 0, 20800200);
    $InitializeCommonEvent(0, 90035012, 20800800, 20800200, 20800201);
    $InitializeCommonEvent(0, 90035013, 20800800, 20800800, 20800200);
    $InitializeCommonEvent(0, 90015000, 20800201, 20800800, 904680320, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 20800800, 15);
    $InitializeCommonEvent(0, 90015030, 20800201, 20800800, 30, 920810, 0);
    $InitializeCommonEvent(0, 9005810, 20800800, 20800500, 20801500, 5);
    $InitializeCommonEvent(0, 90015005, 20801500, 20802800, 20800800);
    $InitializeCommonEvent(0, 90035020, 20800210);
    $InitializeCommonEvent(0, 90035021, 20806420, 20805900, 20800210);
    $InitializeCommonEvent(0, 90035022, 20800200, 20800210);
    $InitializeEvent(0, 20802000);
});

$Event(20802000, Restart, function() {
    WaitFor(EventFlag(20800210));
    DisableAsset(20806202);
});
