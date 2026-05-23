// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90035010, 21100200, 21100210);
    $InitializeCommonEvent(0, 90035011, 21100601, 21101600, 21101610, 21101611, 21106200, 0, 21100200);
    $InitializeCommonEvent(0, 90035012, 21100800, 21100200, 21100201);
    $InitializeCommonEvent(0, 90035013, 21100800, 21100800, 21100200);
    $InitializeCommonEvent(0, 90015000, 21100201, 21100800, 904680320, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 21100800, 15);
    $InitializeCommonEvent(0, 90015030, 21100201, 21100800, 30, 920810, 0);
    $InitializeCommonEvent(0, 9005810, 21100800, 21100500, 21101500, 5);
    $InitializeCommonEvent(0, 90015005, 21101500, 21102800, 21100800);
    $InitializeCommonEvent(0, 90035020, 21100210);
    $InitializeCommonEvent(0, 90035021, 21106420, 21105900, 21100210);
    $InitializeCommonEvent(0, 90035022, 21100200, 21100210);
    $InitializeEvent(0, 21102000);
});

$Event(21102000, Restart, function() {
    WaitFor(EventFlag(21100210));
    DisableAsset(21106202);
});
