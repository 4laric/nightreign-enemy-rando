// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90005580, 1039201970, 1039200970, 7662);
    if (931010 == 0) {
        $InitializeCommonEvent(0, 90015000, 0, 1039200800, 904130700, 30, 0, 0);
        $InitializeCommonEvent(0, 99055500, 1039200800, 15);
        $InitializeCommonEvent(0, 90015030, 0, 1039200800, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015000, 0, 1039200800, 904130700, 30, 0, 0);
        $InitializeCommonEvent(0, 90015030, 0, 1039200800, 30, 931010, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 1039202800, 1039200800, 1020, 931010, 11200, 904130700, 1039200800);
    $InitializeCommonEvent(0, 90015006, 1039201500, 1039200500, 1039202800, 5);
    $InitializeCommonEvent(0, 90015005, 1039201500, 1039202800, 1039202800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S2);
S0:
    GotoIf(S1, 931010 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 1039202800, 940000, 1039200800, 0, 0);
    Goto(S2);
S1:
    $InitializeCommonEvent(0, 90015008, 0, 1039202800, 931010, 1039200800, 0, 0);
S2:
    $InitializeCommonEvent(0, 90015017, 1039200800, 25, 0, 1039202800, 72455, 1039202800);
    $InitializeCommonEvent(0, 90015041, 90, 0, 0, 72481);
    if (921410 == 0) {
        $InitializeCommonEvent(0, 90015000, 0, 1039200810, 903181300, 30, 0, 0);
        $InitializeCommonEvent(0, 99055500, 1039200810, 15);
        $InitializeCommonEvent(0, 90015030, 0, 1039200810, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015000, 0, 1039200810, 903181300, 30, 0, 0);
        $InitializeCommonEvent(0, 90015030, 0, 1039200810, 30, 921410, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 1039202810, 1039200810, 1020, 921410, 11200, 903181300, 1039200810);
    $InitializeCommonEvent(0, 90015006, 1039201510, 1039200510, 1039202810, 5);
    $InitializeCommonEvent(0, 90015005, 1039201510, 1039202810, 1039202810);
    GotoIf(S3, Signed(0) != 0);
    GotoIf(S3, 0 != 0);
    Goto(S5);
S3:
    GotoIf(S4, 921410 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 1039202810, 940000, 1039200810, 0, 0);
    Goto(S5);
S4:
    $InitializeCommonEvent(0, 90015008, 0, 1039202810, 921410, 1039200810, 0, 0);
S5:
    $InitializeCommonEvent(0, 90015017, 1039200810, 25, 0, 1039202810, 72467, 1039202810);
    $InitializeCommonEvent(0, 90015041, 130, 0, 0, 72483);
    $InitializeCommonEvent(0, 90015150, 1039200290, 73088);
    $InitializeCommonEvent(0, 90015151, 1039200290, 74048);
    $InitializeCommonEvent(0, 90015152, 1039200290, 74048);
    $InitializeCommonEvent(0, 90005910, 1039201800, 7687);
    $InitializeCommonEvent(0, 91005505, 1039202510, 7687);
    $InitializeCommonEvent(0, 90065901, 1039204890);
    $InitializeCommonEvent(0, 91005503, 1039201550);
    $InitializeCommonEvent(1, 91005503, 1039201551);
    $InitializeEvent(0, 1039202300, 1039202500);
    $InitializeEvent(0, 1039202220, 1038202350, 1038204350);
});

$Event(1039202300, Restart, function(areaEntityId) {
    DisableNetworkSync();
    WaitFor(InArea(20000, areaEntityId));
    SetSpEffect(20000, 99217);
    RestartEvent();
});

$Event(200, Default, function() {
    $InitializeEvent(0, 1239202200, 1239202600);
});

$Event(1239202200, Restart, function(areaEntityId) {
    DisableNetworkSync();
    if (!CharacterHasSpEffect(20000, 99230)) {
        WaitFor(InArea(20000, areaEntityId));
        SetSpEffect(20000, 99230);
        WaitFixedTimeSeconds(0.1);
    }
L0:
    WaitFor(!InArea(20000, areaEntityId));
    ClearSpEffect(20000, 99230);
    WaitFixedTimeSeconds(0.1);
    RestartEvent();
});

$Event(1039202220, Restart, function(areaEntityId, eventFlagId) {
    DisableNetworkSync();
    if (!EventFlag(eventFlagId)) {
        WaitFor(InArea(20000, areaEntityId));
        SetEventFlagID(eventFlagId, ON);
        WaitFixedTimeSeconds(0.1);
    }
L0:
    WaitFor(!InArea(20000, areaEntityId) && !InArea(20000, 1039202360));
    SetEventFlagID(eventFlagId, OFF);
    WaitFixedTimeSeconds(0.1);
    RestartEvent();
});
