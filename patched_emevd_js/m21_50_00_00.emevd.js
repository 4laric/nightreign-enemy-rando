// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90035010, 21500200, 21500210);
    $InitializeCommonEvent(0, 90035011, 21500601, 21501600, 21501610, 21501611, 21506200, 21507600, 21500200);
    $InitializeCommonEvent(0, 90035012, 21500800, 21500200, 21500201);
    $InitializeCommonEvent(0, 90035013, 21500800, 21500800, 21500200);
    $InitializeCommonEvent(0, 90015000, 21500201, 21500800, 904680320, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 21500800, 15);
    $InitializeCommonEvent(0, 90015030, 21500201, 21500800, 30, 920810, 0);
    $InitializeCommonEvent(0, 9005810, 21500800, 21500500, 21501500, 5);
    $InitializeCommonEvent(0, 90015005, 21501500, 21502800, 21500800);
    $InitializeCommonEvent(0, 90035020, 21500210);
    $InitializeCommonEvent(0, 90035021, 21506420, 21505900, 21500210);
    $InitializeCommonEvent(0, 90035022, 21500200, 21500210);
    $InitializeEvent(0, 21502000);
});

$Event(21502000, Restart, function() {
    WaitFor(EventFlag(21500210));
    DisableAsset(21506202);
});
