// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 99055500, 32200280, 15);
    $InitializeCommonEvent(0, 99055500, 32200281, 15);
    $InitializeCommonEvent(0, 99055500, 32200282, 15);
    $InitializeCommonEvent(0, 99055500, 32200283, 15);
    $InitializeCommonEvent(0, 90015310, 32200050, 32200051, 2, 32200200, 32200202, 32200203, 32202405, 32202406, 32202407, 32202410, 32202411, 32202412, 32202415, 32202416, 32202417, 32202420, 32202421, 32202422, 32202400);
    $InitializeCommonEvent(0, 90015301, 32205300, 32200200, 32200201, 32200202, 32200203, 2);
    $InitializeCommonEvent(0, 90015306, 32206500);
    $InitializeCommonEvent(0, 90015303, 32202401);
    $InitializeCommonEvent(0, 90015305, 32202430, 32202431, 32202432, 32202433);
    $InitializeCommonEvent(0, 90015304, 32200050, 32200200, 32200202);
    if (2 >= 2) {
        $InitializeCommonEvent(0, 90015304, 32200051, 32200200, 32200203);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 32205800, 32202800, 30, 904460000, 0, 0);
        $InitializeCommonEvent(0, 99055500, 32205800, 15);
        $InitializeCommonEvent(0, 90015031, 0, 32205800, 32202800, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 32205800, 32202800, 30, 904460000, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 32205800, 32202800, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 32200800, 32205800, 1030, 940000, 11200, 904460000, 32200500);
    $InitializeCommonEvent(0, 90015006, 32201500, 32200500, 32200800, 5);
    $InitializeCommonEvent(0, 90015005, 32201500, 32202800, 32200800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S2);
S0:
    GotoIf(S1, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 32200800, 940000, 32205800, 0, 0);
    Goto(S2);
S1:
    $InitializeCommonEvent(0, 90015008, 0, 32200800, 940000, 32205800, 0, 0);
S2:
    if (IsMapVariation(0)) {
        $InitializeCommonEvent(0, 90015050, 32200800, 8165);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 32200810, 32202810, 30, 904600600, 0, 0);
        $InitializeCommonEvent(0, 99055500, 32200810, 15);
        $InitializeCommonEvent(0, 90015031, 0, 32200810, 32202810, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 32200810, 32202810, 30, 904600600, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 32200810, 32202810, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 32200810, 32200810, 1030, 940000, 11200, 904600600, 32200810);
    $InitializeCommonEvent(0, 90015006, 32201510, 32200510, 32200810, 5);
    $InitializeCommonEvent(0, 90015005, 32201510, 32202810, 32200810);
    GotoIf(S3, Signed(0) != 0);
    GotoIf(S3, 0 != 0);
    Goto(S5);
S3:
    GotoIf(S4, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 32200810, 940000, 32200810, 0, 0);
    Goto(S5);
S4:
    $InitializeCommonEvent(0, 90015008, 0, 32200810, 940000, 32200810, 0, 0);
S5:
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90015050, 32200810, 8165);
    }
    $InitializeCommonEvent(0, 90035280, 32202491, 32200700, 32200701, 32200702, 8060, 0, 32200800, 32200810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035280, 32202491, 32200700, 32200701, 32200702, 80010, 0, 32200800, 32200810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035280, 32202491, 32200700, 32200701, 32200702, 80011, 1, 32200800, 32200810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035281, 32202491, 32200700, 32200701, 32200702, 80011, 32200800, 32200810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035282, 32200490, 32202490, 32200700, 32200701, 32200702, 32200703);
    $InitializeCommonEvent(0, 90035283, 32200490, 32202491, 32201690, 32200700, 32200701, 32200702, 32200704, 32200705, 32200706);
    $InitializeCommonEvent(0, 90035284, 32205490, 32205491, 32200700, 32200702, 32200705, 32200706);
    $InitializeCommonEvent(0, 90035285, 32200490, 32200700, 32200701, 32200702, 32200705, 32200706);
    $InitializeCommonEvent(0, 90035286, 32200490, 32202491, 32200700, 32200701, 32200702, 32200705, 32200706);
    $InitializeCommonEvent(0, 90035288, 32202491, 32200700, 32200702, 32200705, 32200706);
    $InitializeCommonEvent(0, 90015000, 32200704, 32200490, 907640001, 50, 0, 32200706);
    $InitializeCommonEvent(0, 99055500, 32200490, 15);
    $InitializeCommonEvent(0, 90015025, 8081, 32200704, 32200705, 32200490, 1020, 0, -1, -1, 32200490, 0);
    $InitializeEvent(0, 32202600);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 0, 32200800);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 1, 32200810);
});

$Event(32202600, Restart, function() {
    if (!IsMapVariation(0)) {
        DeleteMapSFX(32202600, false);
        DeleteMapSFX(32202601, false);
        DeleteMapSFX(32202602, false);
        DeleteMapSFX(32202603, false);
        DeleteMapSFX(32202604, false);
        DeleteMapSFX(32202605, false);
        DeleteMapSFX(32202606, false);
        EndEvent();
    }
L0:
    EndEvent();
});
