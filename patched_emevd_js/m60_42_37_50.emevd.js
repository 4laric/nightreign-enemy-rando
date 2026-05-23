// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 99055500, 1027500201, 15);
    $InitializeCommonEvent(0, 99055500, 1027500215, 15);
    RegisterBonfire(1027501950, 0, 5);
    $InitializeCommonEvent(0, 90015004, 1027501950, 1027500951);
    $InitializeEvent(0, 1027502200, 1027502290);
    $InitializeCommonEvent(0, 90005201, 1027500201, 30000, 20000, 30, 2, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005200, 1027500210, 30011, 20011, 1027502210, 0.5, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005200, 1027500211, 30011, 20011, 1027502210, 0.5, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1027500215, 30005, 20005, 30, 2, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1027500220, 30000, 20000, 5, 0.5, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1027500221, 30001, 20001, 5, 0.5, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1027500222, 30000, 20000, 5, 0.5, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1027500223, 30001, 20001, 5, 0.5, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90015450, 1027500200, 1027500200);
    $InitializeCommonEvent(0, 90015000, 0, 1027500800, 903253500, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 1027500800, 15);
    $InitializeCommonEvent(0, 90015030, 0, 1027500800, 30, 920210, 0);
    $InitializeCommonEvent(0, 90015002, 0, 0, 1027500800, 1027500800, 1020, 920210, 11290, 903253500, 1027500800);
    $InitializeCommonEvent(0, 9005810, 1027500800, 1027500500, 1027501500, 5);
    $InitializeCommonEvent(0, 90015005, 1027501500, 1027502800, 1027500800);
    GotoIf(S0, Signed(13801) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S1);
S0:
    $InitializeCommonEvent(0, 90015008, 0, 1027500800, 920210, 1027500800, 13801, 0);
S1:
    if (1 != 0) {
        $InitializeCommonEvent(0, 90015013);
    }
    $InitializeCommonEvent(0, 90015015, 1027500800);
    $InitializeCommonEvent(0, 90015016, 1027500800);
    if (EventFlag(7604)) {
        $InitializeCommonEvent(0, 90015071, 1027500800);
        $InitializeCommonEvent(0, 90015468, 1027500800, 8270, 8247);
    }
    $InitializeCommonEvent(0, 90015017, 1027500800, 15, 0, 1027500800, 72458, 1027500800);
    $InitializeCommonEvent(0, 90015041, 0, 0, 0, 72490);
    $InitializeCommonEvent(0, 90015150, 1027500290, 73096);
    $InitializeCommonEvent(0, 90015151, 1027500290, 74056);
    $InitializeCommonEvent(0, 90015152, 1027500290, 74056);
});

$Event(1027502200, Restart, function(areaEntityId) {
    DisableNetworkSync();
    WaitFor(InArea(20000, areaEntityId));
    SetSpEffect(20000, 99216);
    RestartEvent();
});
