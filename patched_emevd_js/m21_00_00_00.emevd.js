// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90035010, 21000200, 21000210);
    $InitializeCommonEvent(0, 90035011, 21000601, 21001600, 21001610, 21001611, 21006200, 0, 21000200);
    $InitializeCommonEvent(0, 90035012, 21000800, 21000200, 21000201);
    $InitializeCommonEvent(0, 90035013, 21000800, 21000800, 21000200);
    $InitializeCommonEvent(0, 90015000, 21000201, 21000800, 904680320, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 21000800, 15);
    $InitializeCommonEvent(0, 90015030, 21000201, 21000800, 30, 920810, 0);
    $InitializeCommonEvent(0, 9005810, 21000800, 21000500, 21001500, 5);
    $InitializeCommonEvent(0, 90015005, 21001500, 21002800, 21000800);
    $InitializeCommonEvent(0, 90035020, 21000210);
    $InitializeCommonEvent(0, 90035021, 21006420, 21005900, 21000210);
    $InitializeCommonEvent(0, 90035022, 21000200, 21000210);
});

$Event(21002000, Restart, function() {
    WaitFor(EventFlag(21000210));
    DisableAsset(21006202);
});
