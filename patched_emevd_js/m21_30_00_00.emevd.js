// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90035010, 21300200, 21300210);
    $InitializeCommonEvent(0, 90035011, 21300601, 21301600, 21301610, 21301611, 21306200, 0, 21300200);
    $InitializeCommonEvent(0, 90035012, 21300800, 21300200, 21300201);
    $InitializeCommonEvent(0, 90035013, 21300800, 21300800, 21300200);
    $InitializeCommonEvent(0, 90015000, 21300201, 21300800, 904680320, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 21300800, 15);
    $InitializeCommonEvent(0, 90015030, 21300201, 21300800, 30, 920810, 0);
    $InitializeCommonEvent(0, 9005810, 21300800, 21300500, 21301500, 5);
    $InitializeCommonEvent(0, 90015005, 21301500, 21302800, 21300800);
    $InitializeCommonEvent(0, 90035020, 21300210);
    $InitializeCommonEvent(0, 90035021, 21306420, 21305900, 21300210);
    $InitializeCommonEvent(0, 90035022, 21300200, 21300210);
    $InitializeEvent(0, 21302000);
});

$Event(21302000, Restart, function() {
    WaitFor(EventFlag(21300210));
    DisableAsset(21306202);
});
