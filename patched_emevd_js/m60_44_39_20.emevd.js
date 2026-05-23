// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 99055500, 1049200800, 15);
    $InitializeCommonEvent(0, 99055500, 1049200801, 15);
    $InitializeCommonEvent(0, 99055500, 1049200803, 15);
    $InitializeCommonEvent(0, 9005811, 1049202800, 1049201800, 20, 0);
    if (0 == 0) {
        $InitializeCommonEvent(0, 90015000, 0, 1049205800, 903910600, 30, 0, 0);
        $InitializeCommonEvent(0, 99055500, 1049205800, 15);
        $InitializeCommonEvent(0, 90015030, 0, 1049205800, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015000, 0, 1049205800, 903910600, 30, 0, 0);
        $InitializeCommonEvent(0, 90015030, 0, 1049205800, 30, 0, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 1049202800, 1049205800, 1020, 0, 11200, 903910600, 1049200500);
    $InitializeCommonEvent(0, 90015006, 1049201500, 1049200500, 1049202800, 5);
    $InitializeCommonEvent(0, 90015005, 1049201500, 1049202800, 1049202800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S2);
S0:
    GotoIf(S1, 0 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 1049202800, 940000, 1049205800, 0, 0);
    Goto(S2);
S1:
    $InitializeCommonEvent(0, 90015008, 0, 1049202800, 0, 1049205800, 0, 0);
S2:
    $InitializeCommonEvent(0, 90015017, 1049205800, 25, 0, 1049202800, 72456, 1049202800);
    $InitializeCommonEvent(0, 90015041, 20, 0, 0, 72482);
    $InitializeCommonEvent(0, 90015041, 21, 0, 0, 72482);
    $InitializeCommonEvent(0, 90015041, 22, 0, 0, 72482);
    if (931010 == 0) {
        $InitializeCommonEvent(0, 90015000, 0, 1049200810, 904130700, 30, 0, 0);
        $InitializeCommonEvent(0, 99055500, 1049200810, 15);
        $InitializeCommonEvent(0, 90015030, 0, 1049200810, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015000, 0, 1049200810, 904130700, 30, 0, 0);
        $InitializeCommonEvent(0, 90015030, 0, 1049200810, 30, 931010, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 1049202810, 1049200810, 1020, 931010, 11200, 904130700, 1049200810);
    $InitializeCommonEvent(0, 90015006, 1049201510, 1049200510, 1049202810, 5);
    $InitializeCommonEvent(0, 90015005, 1049201510, 1049202810, 1049202810);
    GotoIf(S3, Signed(0) != 0);
    GotoIf(S3, 0 != 0);
    Goto(S5);
S3:
    GotoIf(S4, 931010 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 1049202810, 940000, 1049200810, 0, 0);
    Goto(S5);
S4:
    $InitializeCommonEvent(0, 90015008, 0, 1049202810, 931010, 1049200810, 0, 0);
S5:
    $InitializeCommonEvent(0, 90015017, 1049200810, 25, 0, 1049202810, 72454, 1049202810);
    $InitializeCommonEvent(0, 90015041, 130, 0, 0, 72480);
    if (920310 == 0) {
        $InitializeCommonEvent(0, 90015000, 0, 1049200820, 904505000, 30, 0, 0);
        $InitializeCommonEvent(0, 99055500, 1049200820, 15);
        $InitializeCommonEvent(0, 90015030, 0, 1049200820, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015000, 0, 1049200820, 904505000, 30, 0, 0);
        $InitializeCommonEvent(0, 90015030, 0, 1049200820, 30, 920310, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 1049202820, 1049200820, 1020, 920310, 11200, 904505000, 1049200820);
    $InitializeCommonEvent(0, 90015006, 1049201520, 1049200520, 1049202820, 5);
    $InitializeCommonEvent(0, 90015005, 1049201520, 1049202820, 1049202820);
    GotoIf(S6, Signed(0) != 0);
    GotoIf(S6, 0 != 0);
    Goto(S8);
S6:
    GotoIf(S7, 920310 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 1049202820, 940000, 1049200820, 0, 0);
    Goto(S8);
S7:
    $InitializeCommonEvent(0, 90015008, 0, 1049202820, 920310, 1049200820, 0, 0);
S8:
    $InitializeCommonEvent(0, 90015017, 1049200820, 25, 0, 1049202820, 72468, 1049202820);
    $InitializeCommonEvent(0, 90015041, 0, 0, 0, 72484);
    $InitializeCommonEvent(0, 90015150, 1049200290, 73086);
    $InitializeCommonEvent(0, 90015151, 1049200290, 74046);
    $InitializeCommonEvent(0, 90015152, 1049200290, 74046);
    $InitializeEvent(0, 1049202220, 1049202350, 1049204350);
});

$Event(200, Default, function() {
    $InitializeEvent(0, 1249202500, 1249202511, 1249202510, 350);
});

$Event(1049202220, Restart, function(areaEntityId, eventFlagId) {
    DisableNetworkSync();
    if (!EventFlag(eventFlagId)) {
        WaitFor(InArea(20000, areaEntityId));
        SetEventFlagID(eventFlagId, ON);
        WaitFixedTimeSeconds(0.1);
    }
L0:
    WaitFor(!InArea(20000, areaEntityId) && !InArea(20000, 1049202360));
    SetEventFlagID(eventFlagId, OFF);
    WaitFixedTimeSeconds(0.1);
    RestartEvent();
});

$Event(1249202500, Default, function(entityId, entityId2, targetDistance) {
    DisableNetworkSync();
    if (!EntityInRadiusOfEntity(20000, entityId2, targetDistance, 1)) {
        SpawnMapSFX(entityId);
        WaitFor(EntityInRadiusOfEntity(20000, entityId2, targetDistance, 1));
    }
L0:
    DeleteMapSFX(entityId, true);
    WaitFor(!EntityInRadiusOfEntity(20000, entityId2, targetDistance, 1));
    RestartEvent();
});
