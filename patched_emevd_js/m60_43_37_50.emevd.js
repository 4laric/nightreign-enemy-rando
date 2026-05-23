// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90005580, 1037501950, 1037500950, 7672);
    $InitializeCommonEvent(0, 90065901, 1037504850);
    $InitializeCommonEvent(0, 90005910, 1037501800, 7697);
    $InitializeEvent(0, 91005505, 1037502500, 7697);
    $InitializeCommonEvent(0, 90005201, 1037500200, 30011, 20011, 10, 0.5, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1037500201, 30011, 20011, 3, 0, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1037500202, 30008, 20008, 5, 0, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1037500203, 30010, 20010, 24, 0, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90015150, 1037500290, 73098);
    $InitializeCommonEvent(0, 90015151, 1037500290, 74058);
    $InitializeCommonEvent(0, 90015152, 1037500290, 74058);
    $InitializeCommonEvent(0, 90015000, 0, 1037500800, 905011000, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 1037500800, 15);
    $InitializeCommonEvent(0, 90015030, 0, 1037500800, 30, 920610, 0);
    $InitializeCommonEvent(0, 90015002, 0, 0, 1037500800, 1037500800, 1020, 920610, 11290, 905011000, 1037500800);
    $InitializeCommonEvent(0, 9005810, 1037500800, 1037500500, 1037501500, 5);
    $InitializeCommonEvent(0, 90015005, 1037501500, 1037502800, 1037500800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S1);
S0:
    $InitializeCommonEvent(0, 90015008, 0, 1037500800, 920610, 1037500800, 0, 0);
S1:
    if (0 != 0) {
        $InitializeCommonEvent(0, 90015013);
    }
    $InitializeCommonEvent(0, 90015015, 1037500800);
    $InitializeCommonEvent(0, 90015016, 1037500800);
    if (EventFlag(7604)) {
        $InitializeCommonEvent(0, 90015071, 1037500800);
        $InitializeCommonEvent(0, 90015468, 1037500800, 8270, 8247);
    }
    $InitializeCommonEvent(0, 90015017, 1037500800, 15, 0, 1037500800, 72460, 1037500800);
    $InitializeCommonEvent(0, 90015041, 110, 0, 0, 72492);
});

$Event(100, Default, function() {
    $InitializeEvent(0, 1037502200, 1037502540, 1037504200, 1037502541, 1037502549);
    $InitializeEvent(1, 1037502200, 1037502540, 1037504201, 1037502541, 1037502549);
    $InitializeEvent(2, 1037502200, 1037502541, 1026504200, 0, 0);
    $InitializeEvent(3, 1037502200, 1037502541, 1026504201, 0, 0);
});

$Event(1037502200, Restart, function(areaEntityId, eventFlagId, areaEntityId2, areaEntityId3) {
    DisableNetworkSync();
    if (!EventFlag(eventFlagId)) {
        area |= InArea(20000, areaEntityId);
        if (areaEntityId3 != 0) {
            area |= InArea(20000, areaEntityId3);
        }
        area2 &= area;
        if (areaEntityId2 != 0) {
            area2 &= !InArea(20000, areaEntityId2);
        }
        WaitFor(area2);
        SetEventFlagID(eventFlagId, ON);
        WaitFixedTimeSeconds(0.1);
    }
L0:
    area3 |= InArea(20000, areaEntityId);
    if (areaEntityId3 != 0) {
        area3 |= InArea(20000, areaEntityId3);
    }
    area4 |= !area3;
    if (areaEntityId2 != 0) {
        area4 |= InArea(20000, areaEntityId2);
    }
    WaitFor(area4);
    SetEventFlagID(eventFlagId, OFF);
    WaitFixedTimeSeconds(0.1);
    RestartEvent();
});
