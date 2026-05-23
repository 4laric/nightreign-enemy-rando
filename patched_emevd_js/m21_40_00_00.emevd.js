// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90035010, 21400200, 21400210);
    $InitializeCommonEvent(0, 90035011, 21400601, 21401600, 21401610, 21401611, 21406200, 0, 21400200);
    $InitializeCommonEvent(0, 90035012, 21400800, 21400200, 21400201);
    $InitializeCommonEvent(0, 90035013, 21400800, 21400800, 21400200);
    $InitializeCommonEvent(0, 90015000, 21400201, 21400800, 904680320, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 21400800, 15);
    $InitializeCommonEvent(0, 90015030, 21400201, 21400800, 30, 920810, 0);
    $InitializeCommonEvent(0, 9005810, 21400800, 21400500, 21401500, 5);
    $InitializeCommonEvent(0, 90015005, 21401500, 21402800, 21400800);
    $InitializeCommonEvent(0, 90035020, 21400210);
    $InitializeCommonEvent(0, 90035021, 21406420, 21405900, 21400210);
    $InitializeCommonEvent(0, 90035022, 21400200, 21400210);
    $InitializeEvent(0, 21402000);
});

$Event(21402000, Restart, function() {
    WaitFor(EventFlag(21400210));
    DisableAsset(21406202);
});
