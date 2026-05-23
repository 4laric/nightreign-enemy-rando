// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    if (MissionActive(302)) {
        $InitializeCommonEvent(0, 90085020, 302, 8381, 8382, 8380, 1042380295, 99842, 1042380290, Hero.Ironeye);
        $InitializeCommonEvent(0, 90085021, 302, 8381, 1042382290, 1042380290, Hero.Ironeye);
        if (1 == 1) {
            $InitializeCommonEvent(0, 90085002, 302, 8382, 8381, 1042380290, 1042385290, 1042380290, 0, 0, 0, 63020);
        }
        if (2 == 1) {
            $InitializeCommonEvent(0, 90085002, 302, 8382, 8381, 1042380290, 1042385290, 1042380290, 1042380291, 0, 0, 63020);
        }
        if (3 == 1) {
            $InitializeCommonEvent(0, 90085002, 302, 8382, 8381, 1042380290, 1042385290, 1042380290, 1042380291, 1042380292, 0, 63020);
        }
        if (4 == 1) {
            $InitializeCommonEvent(0, 90085002, 302, 8382, 8381, 1042380290, 1042385290, 1042380290, 1042380291, 1042380292, 1042380293, 63020);
        }
        $InitializeCommonEvent(0, 90085016, 302, 8382, 8381, 1042380290, 1042385290, 1100, 0);
        if (1 == 1) {
            $InitializeCommonEvent(0, 90015000, 8381, 1042380290, 912000030, 30, 0, 8382);
            $InitializeCommonEvent(0, 99055500, 1042380290, 15);
        }
        if (1 != 1) {
            $InitializeCommonEvent(0, 90015000, 8381, 1042385290, 912000030, 30, 0, 8382);
            $InitializeCommonEvent(0, 99055500, 1042385290, 15);
        }
        $InitializeCommonEvent(0, 90015030, 0, 1042385290, 30, 921030, 8382);
    }
    if (MissionActive(302)) {
        $InitializeCommonEvent(0, 90085030, 302, 1042385900);
        $InitializeCommonEvent(0, 90085032, 302, 1042386295);
        $InitializeCommonEvent(0, 90015316, 1042382291);
        $InitializeCommonEvent(0, 90085036, 8381, 11210, Hero.Ironeye, 302);
    }
    $InitializeCommonEvent(0, 91005506, 1042385200);
    $InitializeCommonEvent(0, 90005580, 1042381950, 1042380950, 7651);
    $InitializeCommonEvent(0, 9005810, 1042380800, 1042380951, 1042381951, 5);
    $InitializeCommonEvent(0, 90015005, 1042381951, 1042380951, 1042380800);
    $InitializeCommonEvent(0, 9005810, 1042380805, 1042380952, 1042381952, 5);
    $InitializeCommonEvent(0, 90015005, 1042381952, 1042380952, 1042380805);
    RegisterBonfire(1042381953, 0, 5);
    $InitializeCommonEvent(0, 90015004, 1042381953, 1042380953);
    $InitializeCommonEvent(0, 90015000, 0, 42380800, 903250600, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 42380800, 15);
    $InitializeCommonEvent(0, 90015030, 0, 42380800, 30, 0, 0);
    $InitializeCommonEvent(0, 90015002, 0, 0, 42380800, 42380800, 1020, 0, 11290, 903250600, 42380800);
    $InitializeCommonEvent(0, 9005810, 42380800, 42380500, 42381500, 5);
    $InitializeCommonEvent(0, 90015005, 42381500, 42382800, 42380800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S1);
S0:
    $InitializeCommonEvent(0, 90015008, 0, 42380800, 0, 42380800, 0, 0);
S1:
    if (0 != 0) {
        $InitializeCommonEvent(0, 90015013);
    }
    $InitializeCommonEvent(0, 90015015, 42380800);
    $InitializeCommonEvent(0, 90015016, 42380800);
    if (EventFlag(7604)) {
        $InitializeCommonEvent(0, 90015071, 42380800);
        $InitializeCommonEvent(0, 90015468, 42380800, 8270, 8247);
    }
    $InitializeCommonEvent(0, 90015000, 0, 42380805, 903251600, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 42380805, 15);
    $InitializeCommonEvent(0, 90015030, 0, 42380805, 30, 0, 0);
    $InitializeCommonEvent(0, 90015002, 0, 0, 42380805, 42380805, 1020, 0, 11290, 903251600, 42380805);
    $InitializeCommonEvent(0, 9005810, 42380805, 42380505, 42381505, 5);
    $InitializeCommonEvent(0, 90015005, 42381505, 42382805, 42380805);
    GotoIf(S2, Signed(0) != 0);
    GotoIf(S2, 0 != 0);
    Goto(S3);
S2:
    $InitializeCommonEvent(0, 90015008, 0, 42380805, 0, 42380805, 0, 0);
S3:
    if (0 != 0) {
        $InitializeCommonEvent(0, 90015013);
    }
    $InitializeCommonEvent(0, 90015015, 42380805);
    $InitializeCommonEvent(0, 90015016, 42380805);
    if (EventFlag(7604)) {
        $InitializeCommonEvent(0, 90015071, 42380805);
        $InitializeCommonEvent(0, 90015468, 42380805, 8270, 8247);
    }
    $InitializeCommonEvent(0, 90005910, 1042381800, 7676);
    $InitializeCommonEvent(0, 91005505, 1042382510, 7676);
    $InitializeCommonEvent(0, 90065901, 1042384890);
    $InitializeCommonEvent(0, 90015150, 1042380200, 73057);
    $InitializeCommonEvent(0, 90015151, 1042380200, 74017);
    $InitializeCommonEvent(0, 90015152, 1042380200, 74017);
    $InitializeCommonEvent(0, 90015150, 1042380201, 73058);
    $InitializeCommonEvent(0, 90015151, 1042380201, 74018);
    $InitializeCommonEvent(0, 90015152, 1042380201, 74018);
    $InitializeCommonEvent(0, 91005504, 1042381510, 7605, 0, 0, 0);
    $InitializeCommonEvent(0, 91005504, 1042381500, 7600, 7602, 7603, 0);
    $InitializeCommonEvent(0, 90015140, 1042381200, 200, 9104, 1042388200);
    $InitializeCommonEvent(0, 1042382900, 1042388202, 1042380210);
    $InitializeCommonEvent(1, 1042382900, 1042388203, 1042380211);
    $InitializeCommonEvent(0, 90085001, 801, Hero.Executor, 9251, 9251, 1042381260);
    if (1 == 3) {
        $InitializeCommonEvent(0, 90085002, 801, 9261, 9251, 9251, 1042385260, 1042380260, 0, 0, 0, 20026);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90085002, 801, 9261, 9251, 9251, 1042385260, 1042380260, 1042380261, 0, 0, 20026);
    }
    if (3 == 3) {
        $InitializeCommonEvent(0, 90085002, 801, 9261, 9251, 9251, 1042385260, 1042380260, 1042380261, 1042380262, 0, 20026);
    }
    if (4 == 3) {
        $InitializeCommonEvent(0, 90085002, 801, 9261, 9251, 9251, 1042385260, 1042380260, 1042380261, 1042380262, 1042380263, 20026);
    }
    $InitializeCommonEvent(0, 90085802, 801, 9261, 1042385260);
});

$Event(1042382900, Restart, function(eventFlagId, chrEntityId) {
    EndIf(EventFlag(eventFlagId));
    WaitFor(EventFlag(eventFlagId));
    ForceCharacterTreasure(chrEntityId);
});
