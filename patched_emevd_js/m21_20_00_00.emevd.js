// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90035010, 21200200, 21200210);
    $InitializeCommonEvent(0, 90035011, 21200601, 21201600, 21201610, 21201611, 21206200, 0, 21200200);
    $InitializeCommonEvent(0, 90035012, 21200800, 21200200, 21200201);
    $InitializeCommonEvent(0, 90035013, 21200800, 21200800, 21200200);
    $InitializeCommonEvent(0, 90015000, 21200201, 21200800, 904680320, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 21200800, 15);
    $InitializeCommonEvent(0, 90015030, 21200201, 21200800, 30, 920810, 0);
    $InitializeCommonEvent(0, 9005810, 21200800, 21200500, 21201500, 5);
    $InitializeCommonEvent(0, 90015005, 21201500, 21202800, 21200800);
    $InitializeCommonEvent(0, 90035020, 21200210);
    $InitializeCommonEvent(0, 90035021, 21206420, 21205900, 21200210);
    $InitializeCommonEvent(0, 90035022, 21200200, 21200210);
    $InitializeEvent(0, 21202000);
});

$Event(21202000, Restart, function() {
    WaitFor(EventFlag(21200210));
    DisableAsset(21206202);
});
