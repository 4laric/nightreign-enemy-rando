// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90005580, 1038101958, 1038100958, 7670);
    RegisterBonfire(1038101950, 0, 5);
    $InitializeCommonEvent(0, 90015004, 1038101950, 1038100950);
    $InitializeCommonEvent(0, 90015000, 0, 1038105800, 904602000, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 1038105800, 15);
    $InitializeCommonEvent(0, 90015030, 0, 1038105800, 30, 931010, 0);
    $InitializeCommonEvent(0, 90015002, 0, 0, 1038100800, 1038105800, 1020, 931010, 11290, 904602000, 1038100500);
    $InitializeCommonEvent(0, 9005810, 1038100800, 1038100500, 1038101500, 5);
    $InitializeCommonEvent(0, 90015005, 1038101500, 1038102800, 1038100800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S1);
S0:
    $InitializeCommonEvent(0, 90015008, 0, 1038100800, 931010, 1038105800, 0, 0);
S1:
    if (0 != 0) {
        $InitializeCommonEvent(0, 90015013);
    }
    $InitializeCommonEvent(0, 90015015, 1038100800);
    $InitializeCommonEvent(0, 90015016, 1038100800);
    if (EventFlag(7604)) {
        $InitializeCommonEvent(0, 90015071, 1038100800);
    }
    $InitializeCommonEvent(0, 90015017, 1038100800, 25, 0, 1038102800, 72445, 1038102800);
    $InitializeCommonEvent(0, 90015041, 120, 0, 0, 72476);
    $InitializeCommonEvent(0, 90015041, 121, 0, 0, 72476);
    $InitializeEvent(0, 1038102200, 1038105200, 1038102200);
    $InitializeCommonEvent(0, 90005211, 1038100227, 30000, 20000, 1038102202, 2, 1, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005211, 1038100228, 30000, 20000, 1038102202, 2, 1, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005211, 1038100231, 30000, 20000, 1038102202, 2, 1, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005211, 1038100232, 30000, 20000, 1038102202, 2, 1, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90015150, 1038100290, 73083);
    $InitializeCommonEvent(0, 90015151, 1038100290, 73043);
    $InitializeCommonEvent(0, 90015152, 1038100290, 73043);
    $InitializeCommonEvent(0, 90005910, 1038101805, 7695);
    $InitializeCommonEvent(0, 91005505, 1038102510, 7695);
    $InitializeCommonEvent(0, 90065901, 1038104890);
});

$Event(1038102200, Restart, function(chrEntityId, areaEntityId) {
    ClearSpEffect(chrEntityId, 4800);
    ClearSpEffect(chrEntityId, 5665);
    EndIf(EventFlag(1038100200));
    SetSpEffect(chrEntityId, 4800);
    SetSpEffect(chrEntityId, 5665);
    WaitFor(
        HasDamageType(chrEntityId, 20000, DamageType.Any)
            || EntityInRadiusOfEntity(20000, chrEntityId, 10, 1)
            || InArea(20000, areaEntityId));
    SetNetworkconnectedEventFlagID(1038100200, ON);
    ClearSpEffect(chrEntityId, 4800);
    ClearSpEffect(chrEntityId, 5665);
});
