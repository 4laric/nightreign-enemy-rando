// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90015310, 38100050, 38100051, 1, 38100200, 38100202, 38100203, 38102405, 38102406, 38102407, 38102410, 38102411, 38102412, 38102415, 38102416, 38102417, 38102420, 38102421, 38102422, 38102400);
    $InitializeCommonEvent(0, 90015301, 38105300, 38100200, 38100201, 38100202, 38100203, 1);
    $InitializeCommonEvent(0, 90015306, 38106500);
    $InitializeCommonEvent(0, 90015303, 38102401);
    $InitializeCommonEvent(0, 90015305, 38102430, 38102431, 38102432, 38102433);
    $InitializeCommonEvent(0, 90015304, 38100050, 38100200, 38100202);
    if (1 >= 2) {
        $InitializeCommonEvent(0, 90015304, 38100051, 38100200, 38100203);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 38100800, 38102800, 30, 903900000, 0, 0);
        $InitializeCommonEvent(0, 99055500, 38100800, 15);
        $InitializeCommonEvent(0, 90015031, 0, 38100800, 38102800, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 38100800, 38102800, 30, 903900000, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 38100800, 38102800, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 38100800, 38100800, 1030, 940000, 11200, 903900000, 38100800);
    $InitializeCommonEvent(0, 90015006, 38101500, 38100500, 38100800, 5);
    $InitializeCommonEvent(0, 90015005, 38101500, 38102800, 38100800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S2);
S0:
    GotoIf(S1, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 38100800, 940000, 38100800, 0, 0);
    Goto(S2);
S1:
    $InitializeCommonEvent(0, 90015008, 0, 38100800, 940000, 38100800, 0, 0);
S2:
    $InitializeCommonEvent(0, 90005250, 38100800, 38102800, 0, -1);
    if (IsMapVariation(0)) {
        $InitializeCommonEvent(0, 90015050, 38100800, 8175);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 38100810, 38102810, 30, 904355000, 0, 0);
        $InitializeCommonEvent(0, 99055500, 38100810, 15);
        $InitializeCommonEvent(0, 90015031, 0, 38100810, 38102810, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 38100810, 38102810, 30, 904355000, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 38100810, 38102810, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 38100810, 38100810, 1030, 940000, 11200, 904355000, 38100810);
    $InitializeCommonEvent(0, 90015006, 38101510, 38100510, 38100810, 5);
    $InitializeCommonEvent(0, 90015005, 38101510, 38102810, 38100810);
    GotoIf(S3, Signed(0) != 0);
    GotoIf(S3, 0 != 0);
    Goto(S5);
S3:
    GotoIf(S4, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 38100810, 940000, 38100810, 0, 0);
    Goto(S5);
S4:
    $InitializeCommonEvent(0, 90015008, 0, 38100810, 940000, 38100810, 0, 0);
S5:
    $InitializeCommonEvent(0, 90005250, 38100810, 38102810, 0, -1);
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90015050, 38100810, 8175);
    }
    $InitializeCommonEvent(0, 90035280, 38102491, 38100700, 38100701, 38100702, 8060, 0, 38100800, 38100810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035280, 38102491, 38100700, 38100701, 38100702, 80010, 0, 38100800, 38100810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035280, 38102491, 38100700, 38100701, 38100702, 80011, 1, 38100800, 38100810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035281, 38102491, 38100700, 38100701, 38100702, 80011, 38100800, 38100810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035282, 38100490, 38102490, 38100700, 38100701, 38100702, 38100703);
    $InitializeCommonEvent(0, 90035283, 38100490, 38102491, 38101690, 38100700, 38100701, 38100702, 38100704, 38100705, 38100706);
    $InitializeCommonEvent(0, 90035284, 38105490, 38105491, 38100700, 38100702, 38100705, 38100706);
    $InitializeCommonEvent(0, 90035285, 38100490, 38100700, 38100701, 38100702, 38100705, 38100706);
    $InitializeCommonEvent(0, 90035286, 38100490, 38102491, 38100700, 38100701, 38100702, 38100705, 38100706);
    $InitializeCommonEvent(0, 90035288, 38102491, 38100700, 38100702, 38100705, 38100706);
    $InitializeCommonEvent(0, 90015000, 38100704, 38100490, 907640001, 50, 0, 38100706);
    $InitializeCommonEvent(0, 99055500, 38100490, 15);
    $InitializeCommonEvent(0, 90015025, 8081, 38100704, 38100705, 38100490, 1020, 0, -1, -1, 38100490, 0);
    $InitializeCommonEvent(0, 90005250, 38100200, 38102200, 0, -1);
    $InitializeCommonEvent(0, 90005250, 38100201, 38102200, 0, -1);
    $InitializeCommonEvent(0, 90005250, 38100202, 38102200, 0, -1);
    $InitializeCommonEvent(0, 90005250, 38100203, 38102200, 0, -1);
    $InitializeCommonEvent(0, 90005250, 38100304, 38102302, 0, -1);
    $InitializeCommonEvent(0, 90005250, 38100305, 38102302, 0, -1);
    $InitializeCommonEvent(0, 90005250, 38100306, 38102302, 0, -1);
    $InitializeCommonEvent(0, 90005250, 38100307, 38102302, 0, -1);
    $InitializeCommonEvent(0, 90005250, 38100350, 38102302, 0, -1);
    $InitializeCommonEvent(0, 90005250, 38100351, 38102302, 0, -1);
    $InitializeCommonEvent(0, 90005250, 38100308, 38102304, 0, -1);
    $InitializeCommonEvent(0, 90005250, 38100309, 38102304, 0, -1);
    $InitializeCommonEvent(0, 90005250, 38100310, 38102304, 0, -1);
    $InitializeCommonEvent(0, 90005250, 38100311, 38102304, 0, -1);
    $InitializeCommonEvent(0, 90005250, 38100322, 38102306, 0, -1);
    $InitializeCommonEvent(0, 90005250, 38100323, 38102306, 0, -1);
    $InitializeCommonEvent(0, 90005250, 38100352, 38102306, 0, -1);
    $InitializeCommonEvent(0, 90005250, 38100353, 38102306, 0, -1);
    $InitializeEvent(0, 38102700);
    $InitializeEvent(0, 38102720);
    $InitializeEvent(0, 38102710);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 0, 38100800);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 1, 38100810);
});

$Event(38102700, Restart, function() {
    if (!EventFlag(38102711)) {
        ForceAnimationPlayback(38101200, 0, true, false, false);
        ForceAnimationPlayback(38101201, 0, true, false, false);
        EndEvent();
    }
L0:
    ForceAnimationPlayback(38101200, 2, true, false, false);
    ForceAnimationPlayback(38101201, 2, true, false, false);
    EndEvent();
});

$Event(38102710, Restart, function() {
    if (!EventFlag(38102711)) {
        WaitFor(InArea(20000, 38102820));
        EndIf(EventFlag(38102711));
        ForceAnimationPlayback(38101210, 1, false, true, false);
        SetNetworkconnectedEventFlagID(38102711, ON);
    }
    ForceAnimationPlayback(38101210, 2, true, false, false);
});

$Event(38102720, End, function() {
    WaitFor(EventFlag(38102711));
    ForceAnimationPlayback(38101200, 1, false, false, false);
    ForceAnimationPlayback(38101201, 1, false, true, false);
});

$Event(38102990, Default, function() {
    DisableNetworkSync();
    ClearSpEffect(20000, 99175);
    EndIf(!IsHotSpot());
    WaitFor(InArea(20000, 38102402));
    SetSpEffect(20000, 99175);
    WaitFixedTimeFrames(1);
    WaitFor(!InArea(20000, 38102402));
    ClearSpEffect(20000, 99175);
    RestartEvent();
});
