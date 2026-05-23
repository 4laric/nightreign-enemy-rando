// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90015310, 34100050, 34100051, 2, 34100200, 34100202, 34100203, 34102405, 34102406, 34102407, 34102410, 34102411, 34102412, 34102415, 34102416, 34102417, 34102420, 34102421, 34102422, 34102400);
    $InitializeCommonEvent(0, 90015301, 34105300, 34100200, 34100201, 34100202, 34100203, 2);
    $InitializeCommonEvent(0, 90015306, 34106500);
    $InitializeCommonEvent(0, 90015303, 34102401);
    $InitializeCommonEvent(0, 90015305, 34102430, 34102431, 34102432, 34102433);
    $InitializeCommonEvent(0, 90015304, 34100050, 34100200, 34100202);
    if (2 >= 2) {
        $InitializeCommonEvent(0, 90015304, 34100051, 34100200, 34100203);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 34100800, 34102800, 30, 903701000, 0, 0);
        $InitializeCommonEvent(0, 99055500, 34100800, 15);
        $InitializeCommonEvent(0, 90015031, 0, 34100800, 34102800, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 34100800, 34102800, 30, 903701000, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 34100800, 34102800, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 34100800, 34100800, 1030, 940000, 11200, 903701000, 34100800);
    $InitializeCommonEvent(0, 90015006, 34101500, 34100500, 34100800, 5);
    $InitializeCommonEvent(0, 90015005, 34101500, 34102800, 34100800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S2);
S0:
    GotoIf(S1, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 34100800, 940000, 34100800, 0, 0);
    Goto(S2);
S1:
    $InitializeCommonEvent(0, 90015008, 0, 34100800, 940000, 34100800, 0, 0);
S2:
    if (IsMapVariation(0)) {
        $InitializeCommonEvent(0, 90015050, 34100800, 8170);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 34100810, 34102810, 30, 903700301, 0, 0);
        $InitializeCommonEvent(0, 99055500, 34100810, 15);
        $InitializeCommonEvent(0, 90015031, 0, 34100810, 34102810, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 34100810, 34102810, 30, 903700301, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 34100810, 34102810, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 34100810, 34100810, 1030, 940000, 11200, 903700301, 34100810);
    $InitializeCommonEvent(0, 90015006, 34101510, 34100510, 34100810, 5);
    $InitializeCommonEvent(0, 90015005, 34101510, 34102810, 34100810);
    GotoIf(S3, Signed(0) != 0);
    GotoIf(S3, 0 != 0);
    Goto(S5);
S3:
    GotoIf(S4, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 34100810, 940000, 34100810, 0, 0);
    Goto(S5);
S4:
    $InitializeCommonEvent(0, 90015008, 0, 34100810, 940000, 34100810, 0, 0);
S5:
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90015050, 34100810, 8170);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 34105820, 34102820, 30, 903704522, 0, 0);
        $InitializeCommonEvent(0, 99055500, 34105820, 15);
        $InitializeCommonEvent(0, 90015031, 0, 34105820, 34102820, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 34105820, 34102820, 30, 903704522, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 34105820, 34102820, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 34100820, 34105820, 1030, 940000, 11200, 903704522, 34100520);
    $InitializeCommonEvent(0, 90015006, 34101520, 34100520, 34100820, 5);
    $InitializeCommonEvent(0, 90015005, 34101520, 34102820, 34100820);
    GotoIf(S6, Signed(0) != 0);
    GotoIf(S6, 0 != 0);
    Goto(S8);
S6:
    GotoIf(S7, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 34100820, 940000, 34105820, 0, 0);
    Goto(S8);
S7:
    $InitializeCommonEvent(0, 90015008, 0, 34100820, 940000, 34105820, 0, 0);
S8:
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015050, 34100820, 8170);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 34105830, 34102830, 30, 903180000, 0, 0);
        $InitializeCommonEvent(0, 99055500, 34105830, 15);
        $InitializeCommonEvent(0, 90015031, 0, 34105830, 34102830, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 34105830, 34102830, 30, 903180000, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 34105830, 34102830, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 34100830, 34105830, 1030, 940000, 11200, 903180000, 34100530);
    $InitializeCommonEvent(0, 90015006, 34101530, 34100530, 34100830, 5);
    $InitializeCommonEvent(0, 90015005, 34101530, 34102830, 34100830);
    GotoIf(S9, Signed(0) != 0);
    GotoIf(S9, 0 != 0);
    Goto(S11);
S9:
    GotoIf(S10, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 34100830, 940000, 34105830, 0, 0);
    Goto(S11);
S10:
    $InitializeCommonEvent(0, 90015008, 0, 34100830, 940000, 34105830, 0, 0);
S11:
    if (IsMapVariation(3)) {
        $InitializeCommonEvent(0, 90015050, 34100830, 8170);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 34100840, 34102840, 30, 904630310, 0, 0);
        $InitializeCommonEvent(0, 99055500, 34100840, 15);
        $InitializeCommonEvent(0, 90015031, 0, 34100840, 34102840, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 34100840, 34102840, 30, 904630310, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 34100840, 34102840, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 34100840, 34100840, 1030, 940000, 11200, 904630310, 34100840);
    $InitializeCommonEvent(0, 90015006, 34101540, 34100540, 34100840, 5);
    $InitializeCommonEvent(0, 90015005, 34101540, 34102840, 34100840);
    GotoIf(S12, Signed(0) != 0);
    GotoIf(S12, 0 != 0);
    Goto(S14);
S12:
    GotoIf(S13, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 34100840, 940000, 34100840, 0, 0);
    Goto(S14);
S13:
    $InitializeCommonEvent(0, 90015008, 0, 34100840, 940000, 34100840, 0, 0);
S14:
    if (IsMapVariation(4)) {
        $InitializeCommonEvent(0, 90015050, 34100840, 8170);
    }
    $InitializeCommonEvent(0, 90035280, 34102491, 34100700, 34100701, 34100702, 8060, 0, 34100800, 34100810, 34100820, 34100830, 34100840);
    $InitializeCommonEvent(0, 90035280, 34102491, 34100700, 34100701, 34100702, 80010, 0, 34100800, 34100810, 34100820, 34100830, 34100840);
    $InitializeCommonEvent(0, 90035280, 34102491, 34100700, 34100701, 34100702, 80011, 1, 34100800, 34100810, 34100820, 34100830, 34100840);
    $InitializeCommonEvent(0, 90035281, 34102491, 34100700, 34100701, 34100702, 80011, 34100800, 34100810, 34100820, 34100830, 34100840);
    $InitializeCommonEvent(0, 90035282, 34100490, 34102490, 34100700, 34100701, 34100702, 34100703);
    $InitializeCommonEvent(0, 90035283, 34100490, 34102491, 34101690, 34100700, 34100701, 34100702, 34100704, 34100705, 34100706);
    $InitializeCommonEvent(0, 90035284, 34105490, 34105491, 34100700, 34100702, 34100705, 34100706);
    $InitializeCommonEvent(0, 90035285, 34100490, 34100700, 34100701, 34100702, 34100705, 34100706);
    $InitializeCommonEvent(0, 90035286, 34100490, 34102491, 34100700, 34100701, 34100702, 34100705, 34100706);
    $InitializeCommonEvent(0, 90035288, 34102491, 34100700, 34100702, 34100705, 34100706);
    $InitializeCommonEvent(0, 90015000, 34100704, 34100490, 907640001, 50, 0, 34100706);
    $InitializeCommonEvent(0, 99055500, 34100490, 15);
    $InitializeCommonEvent(0, 90015025, 8081, 34100704, 34100705, 34100490, 1020, 0, -1, -1, 34100490, 0);
    $InitializeCommonEvent(0, 90005526, 34100500, 34101200);
    $InitializeEvent(0, 34102600);
    $InitializeEvent(0, 34102630);
    $InitializeEvent(0, 34102640);
    $InitializeCommonEvent(0, 90015010, 34101280, 34100280, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(1, 90015010, 34101281, 34100281, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(2, 90015010, 34101282, 34100282, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(3, 90015010, 34101283, 34100283, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(4, 90015010, 34101284, 34100284, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(5, 90015010, 34101285, 34100285, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(6, 90015010, 34101286, 34100286, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(7, 90015010, 34101287, 34100287, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(8, 90015010, 34101288, 34100288, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(9, 90015010, 34101289, 34100289, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(10, 90015010, 34101290, 34100290, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(11, 90015010, 34101291, 34100291, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(12, 90015010, 34101292, 34100292, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(13, 90015010, 34101293, 34100293, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(14, 90015010, 34101294, 34100294, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(15, 90015010, 34101295, 34100295, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(16, 90015010, 34101296, 34100296, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(17, 90015010, 34101297, 34100297, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(18, 90015010, 34101298, 34100298, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(19, 90015010, 34101299, 34100299, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(20, 90015010, 34101300, 34100300, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(21, 90015010, 34101301, 34100301, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(22, 90015010, 34101302, 34100302, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(23, 90015010, 34101303, 34100303, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(24, 90015010, 34101304, 34100304, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(25, 90015010, 34101305, 34100305, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(26, 90015010, 34101306, 34100306, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(27, 90015010, 34101307, 34100307, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(28, 90015010, 34101308, 34100308, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(29, 90015010, 34101309, 34100309, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(30, 90015010, 34101310, 34100310, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(31, 90015010, 34101311, 34100311, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(32, 90015010, 34101312, 34100312, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(33, 90015010, 34101313, 34100313, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(34, 90015010, 34101314, 34100314, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(35, 90015010, 34101315, 34100315, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(36, 90015010, 34101316, 34100316, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(37, 90015010, 34101317, 34100317, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(38, 90015010, 34101318, 34100318, 34100280, 100, 803400000, 4);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 0, 34100800);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 1, 34100810);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 2, 34100820);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 3, 34100830);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 4, 34100840);
});

$Event(34102600, Restart, function() {
    if (!IsMapVariation(0)) {
        DeleteMapSFX(34102600, false);
        EndEvent();
    }
L0:
    EndEvent();
});

$Event(34102630, Restart, function() {
    if (!IsMapVariation(3)) {
        DeleteMapSFX(34102601, false);
        DeleteMapSFX(34102602, false);
        DeleteMapSFX(34102603, false);
        DeleteMapSFX(34102604, false);
        DeleteMapSFX(34102605, false);
        DeleteMapSFX(34102606, false);
        DeleteMapSFX(34102607, false);
        DeleteMapSFX(34102608, false);
        DeleteMapSFX(34102609, false);
        DeleteMapSFX(34102610, false);
        DeleteMapSFX(34102611, false);
        DeleteMapSFX(34102612, false);
        DeleteMapSFX(34102613, false);
        DeleteMapSFX(34102629, false);
        DeleteMapSFX(34102630, false);
        EndEvent();
    }
L0:
    EndEvent();
});

$Event(34102640, Restart, function() {
    if (!IsMapVariation(4)) {
        DeleteMapSFX(34102614, false);
        DeleteMapSFX(34102615, false);
        DeleteMapSFX(34102616, false);
        DeleteMapSFX(34102617, false);
        DeleteMapSFX(34102618, false);
        DeleteMapSFX(34102619, false);
        DeleteMapSFX(34102620, false);
        DeleteMapSFX(34102621, false);
        DeleteMapSFX(34102622, false);
        DeleteMapSFX(34102623, false);
        DeleteMapSFX(34102624, false);
        DeleteMapSFX(34102625, false);
        DeleteMapSFX(34102626, false);
        DeleteMapSFX(34102627, false);
        DeleteMapSFX(34102628, false);
        EndEvent();
    }
L0:
    EndEvent();
});

$Event(34102800, Default, function() {
    SetSpEffect(0, 0);
});

$Event(34102810, Restart, function() {
    WaitFor(
        EventFlag(34102800)
            && (InArea(10000, 34102890)
                || InArea(10001, 34102890)
                || InArea(10002, 34102890)
                || CharacterAIState(34100800, AIStateType.Combat)));
    DisplayBossHealthBar(Enabled, 34100800, 0, 903700301);
    SetEventFlagID(34102812, ON);
});

$Event(34102811, Restart, function() {
    DisableNetworkSync();
    if (!EventFlag(34102830)) {
        WaitFor(EventFlag(34102810) && EntityInRadiusOfEntity(20000, 34100800, 30, 1));
        if (!EventFlag(34102812)) {
            DisplayBossHealthBar(Enabled, 34100800, 0, 903700301);
        }
L1:
        WaitFor(EventFlag(34102810) && !EntityInRadiusOfEntity(20000, 34100800, 30, 1));
        DisplayBossHealthBar(Disabled, 34100800, 0, 903700301);
        SetEventFlagID(34102812, OFF);
        RestartEvent();
    }
L0:
    EndEvent();
});

$Event(34102820, Default, function() {
    WaitFor(EventFlag(34102810));
    SetSpEffect(0, 0);
});

$Event(34102830, Default, function() {
    WaitFor(EventFlag(34102820));
    WaitFor(CharacterHPValue(34100800) <= 0);
    PlaySE(34100800, SoundType.SFX, 888880000);
    HandleMinibossDefeat(3410080);
    DisplayBossHealthBar(Disabled, 34100800, 0, 903700301);
    SetNetworkconnectedEventFlagID(34100800, ON);
});

$Event(34102840, Default, function() {
    WaitFor(EventFlag(34102830));
    SetSpEffect(0, 0);
});

$Event(34102850, Default, function() {
    SetSpEffect(0, 0);
});

$Event(34102860, Restart, function() {
    DisableNetworkSync();
    area = EntityInRadiusOfEntity(34100820, 20000, 30, 1) || EntityInRadiusOfEntity(34100821, 20000, 30, 1);
    chr = CharacterAIState(34100820, AIStateType.Combat) || CharacterAIState(34100821, AIStateType.Combat);
    WaitFor(EventFlag(34102850) && chr && area);
    DisplayBossHealthBar(Enabled, 34100820, 0, 904260300);
    DisplayBossHealthBar(Enabled, 34100821, 1, 904260301);
    SetEventFlagID(34102862, ON);
});

$Event(34102861, Restart, function() {
    DisableNetworkSync();
    WaitFor(
        EventFlag(34102860)
            && (EntityInRadiusOfEntity(20000, 34100820, 40, 1)
                || EntityInRadiusOfEntity(20000, 34100821, 40, 1)));
    if (!EventFlag(34102880)) {
        if (!EventFlag(34102862)) {
            DisplayBossHealthBar(Enabled, 34100820, 0, 904260300);
            DisplayBossHealthBar(Enabled, 34100821, 1, 904260301);
        }
L1:
        WaitFor(
            EventFlag(34102860)
                && !EntityInRadiusOfEntity(20000, 34100820, 40, 1)
                && !EntityInRadiusOfEntity(20000, 34100821, 40, 1));
        DisplayBossHealthBar(Disabled, 34100820, 0, 904260300);
        DisplayBossHealthBar(Disabled, 34100821, 1, 904260301);
        SetEventFlagID(34102862, OFF);
        RestartEvent();
    }
L0:
    EndEvent();
});

$Event(34102870, Default, function() {
    WaitFor(EventFlag(34102860));
    SetSpEffect(0, 0);
});

$Event(34102880, Default, function() {
    WaitFor(
        EventFlag(34102870) && CharacterHPValue(34100820) <= 0 && CharacterHPValue(34100821) <= 0);
    PlaySE(34100820, SoundType.SFX, 888880000);
    HandleMinibossDefeat(34100820);
    DisplayBossHealthBar(Disabled, 34100820, 0, 904260300);
    DisplayBossHealthBar(Disabled, 34100821, 1, 904260301);
    SetNetworkconnectedEventFlagID(34100820, ON);
});

$Event(34102890, Default, function() {
    WaitFor(EventFlag(34102880));
    SetSpEffect(0, 0);
});
