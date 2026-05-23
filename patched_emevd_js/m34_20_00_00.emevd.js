// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90015310, 34200050, 34200051, 2, 34200200, 34200202, 34200203, 34202405, 34202406, 34202407, 34202410, 34202411, 34202412, 34202415, 34202416, 34202417, 34202420, 34202421, 34202422, 34202400);
    $InitializeCommonEvent(0, 90015301, 34205300, 34200200, 34200201, 34200202, 34200203, 2);
    $InitializeCommonEvent(0, 90015306, 34206500);
    $InitializeCommonEvent(0, 90015303, 34202401);
    $InitializeCommonEvent(0, 90015305, 34202430, 34202431, 34202432, 34202433);
    $InitializeCommonEvent(0, 90015304, 34200050, 34200200, 34200202);
    if (2 >= 2) {
        $InitializeCommonEvent(0, 90015304, 34200051, 34200200, 34200203);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 34200800, 34202800, 30, 904580601, 0, 0);
        $InitializeCommonEvent(0, 99055500, 34200800, 15);
        $InitializeCommonEvent(0, 90015031, 0, 34200800, 34202800, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 34200800, 34202800, 30, 904580601, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 34200800, 34202800, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 34200800, 34200800, 1030, 940000, 11200, 904580601, 34200800);
    $InitializeCommonEvent(0, 90015006, 34201500, 34200500, 34200800, 5);
    $InitializeCommonEvent(0, 90015005, 34201500, 34202800, 34200800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S2);
S0:
    GotoIf(S1, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 34200800, 940000, 34200800, 0, 0);
    Goto(S2);
S1:
    $InitializeCommonEvent(0, 90015008, 0, 34200800, 940000, 34200800, 0, 0);
S2:
    if (IsMapVariation(0)) {
        $InitializeCommonEvent(0, 90015050, 34200800, 8170);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 34205810, 34202810, 30, 903970313, 0, 0);
        $InitializeCommonEvent(0, 99055500, 34205810, 15);
        $InitializeCommonEvent(0, 90015031, 0, 34205810, 34202810, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 34205810, 34202810, 30, 903970313, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 34205810, 34202810, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 34200810, 34205810, 1030, 940000, 11200, 903970313, 34200510);
    $InitializeCommonEvent(0, 90015006, 34201510, 34200510, 34200810, 5);
    $InitializeCommonEvent(0, 90015005, 34201510, 34202810, 34200810);
    GotoIf(S3, Signed(0) != 0);
    GotoIf(S3, 0 != 0);
    Goto(S5);
S3:
    GotoIf(S4, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 34200810, 940000, 34205810, 0, 0);
    Goto(S5);
S4:
    $InitializeCommonEvent(0, 90015008, 0, 34200810, 940000, 34205810, 0, 0);
S5:
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90015050, 34200810, 8170);
    }
    $InitializeCommonEvent(0, 90035280, 34202491, 34200700, 34200701, 34200702, 8060, 0, 34200800, 34200810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035280, 34202491, 34200700, 34200701, 34200702, 80010, 0, 34200800, 34200810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035280, 34202491, 34200700, 34200701, 34200702, 80011, 1, 34200800, 34200810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035281, 34202491, 34200700, 34200701, 34200702, 80011, 34200800, 34200810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035282, 34200490, 34202490, 34200700, 34200701, 34200702, 34200703);
    $InitializeCommonEvent(0, 90035283, 34200490, 34202491, 34201690, 34200700, 34200701, 34200702, 34200704, 34200705, 34200706);
    $InitializeCommonEvent(0, 90035284, 34205490, 34205491, 34200700, 34200702, 34200705, 34200706);
    $InitializeCommonEvent(0, 90035285, 34200490, 34200700, 34200701, 34200702, 34200705, 34200706);
    $InitializeCommonEvent(0, 90035286, 34200490, 34202491, 34200700, 34200701, 34200702, 34200705, 34200706);
    $InitializeCommonEvent(0, 90035288, 34202491, 34200700, 34200702, 34200705, 34200706);
    $InitializeCommonEvent(0, 90015000, 34200704, 34200490, 907640001, 50, 0, 34200706);
    $InitializeCommonEvent(0, 99055500, 34200490, 15);
    $InitializeCommonEvent(0, 90015025, 8081, 34200704, 34200705, 34200490, 1020, 0, -1, -1, 34200490, 0);
    $InitializeCommonEvent(0, 90005526, 34200500, 34201200);
    $InitializeEvent(0, 34202600);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 0, 34200800);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 1, 34200810);
});

$Event(34202600, Restart, function() {
    if (!IsMapVariation(0)) {
        DeleteMapSFX(34202600, false);
        DeleteMapSFX(34202601, false);
        EndEvent();
    }
L0:
    EndEvent();
});
