// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 99055500, 1026500200, 15);
    $InitializeCommonEvent(0, 99055500, 1026500250, 15);
    $InitializeCommonEvent(0, 99055500, 1026500251, 15);
    $InitializeCommonEvent(0, 99055500, 1026500252, 15);
    $InitializeCommonEvent(0, 99055500, 1026500253, 15);
    $InitializeEvent(0, 1026502220);
    RegisterBonfire(1026501950, 0, 5);
    $InitializeCommonEvent(0, 90015004, 1026501950, 1026500950);
    RegisterBonfire(1026501951, 0, 5);
    $InitializeCommonEvent(0, 90015004, 1026501951, 1026500951);
    RegisterBonfire(1026501952, 0, 5);
    $InitializeCommonEvent(0, 90015004, 1026501952, 1026500952);
    $InitializeCommonEvent(0, 90015000, 0, 1026500800, 904620320, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 1026500800, 15);
    $InitializeCommonEvent(0, 90015030, 0, 1026500800, 30, 920710, 0);
    $InitializeCommonEvent(0, 90015002, 0, 0, 1026500800, 1026500800, 1020, 920710, 11290, 904620320, 1026500800);
    $InitializeCommonEvent(0, 9005810, 1026500800, 1026500500, 1026501500, 5);
    $InitializeCommonEvent(0, 90015005, 1026501500, 1026502800, 1026500800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 1058642330 != 0);
    Goto(S1);
S0:
    $InitializeCommonEvent(0, 90015008, 0, 1026500800, 920710, 1026500800, 0, 0.6);
S1:
    if (0 != 0) {
        $InitializeCommonEvent(0, 90015013);
    }
    $InitializeCommonEvent(0, 90015015, 1026500800);
    $InitializeCommonEvent(0, 90015016, 1026500800);
    if (EventFlag(7604)) {
        $InitializeCommonEvent(0, 90015071, 1026500800);
        $InitializeCommonEvent(0, 90015468, 1026500800, 8270, 8247);
    }
    $InitializeCommonEvent(0, 90015017, 1026500800, 30, 0, 1026500800, 72449, 1026500800);
    $InitializeCommonEvent(0, 90005211, 1026500800, 30017, 20017, 1026502550, 30, 3, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 9005811, 1026500800, 1026501800, 20, 0);
    $InitializeCommonEvent(0, 90015000, 0, 1026500810, 904600200, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 1026500810, 15);
    $InitializeCommonEvent(0, 90015030, 0, 1026500810, 30, 931010, 0);
    $InitializeCommonEvent(0, 90015002, 0, 0, 1026500810, 1026500810, 1020, 931010, 11290, 904600200, 1026500810);
    $InitializeCommonEvent(0, 9005810, 1026500810, 1026500510, 1026501510, 5);
    $InitializeCommonEvent(0, 90015005, 1026501510, 1026502810, 1026500810);
    GotoIf(S2, Signed(0) != 0);
    GotoIf(S2, 0 != 0);
    Goto(S3);
S2:
    $InitializeCommonEvent(0, 90015008, 0, 1026500810, 931010, 1026500810, 0, 0);
S3:
    if (0 != 0) {
        $InitializeCommonEvent(0, 90015013);
    }
    $InitializeCommonEvent(0, 90015015, 1026500810);
    $InitializeCommonEvent(0, 90015016, 1026500810);
    if (EventFlag(7604)) {
        $InitializeCommonEvent(0, 90015071, 1026500810);
        $InitializeCommonEvent(0, 90015468, 1026500810, 8270, 8247);
    }
    $InitializeCommonEvent(0, 90015017, 1026500810, 15, 0, 1026500810, 72452, 1026500810);
    $InitializeCommonEvent(0, 90015041, 190, 0, 0, 72487);
    $InitializeCommonEvent(0, 90005201, 1026500810, 30000, 20000, 30, 2, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90015000, 0, 1026500850, 904650601, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 1026500850, 15);
    $InitializeCommonEvent(0, 90015030, 0, 1026500850, 30, 920310, 0);
    $InitializeCommonEvent(0, 90015002, 0, 0, 1026500850, 1026500850, 1020, 920310, 11290, 904650601, 1026500850);
    $InitializeCommonEvent(0, 9005810, 1026500850, 1026500550, 1026501550, 5);
    $InitializeCommonEvent(0, 90015005, 1026501550, 1026502850, 1026500850);
    GotoIf(S4, Signed(0) != 0);
    GotoIf(S4, 0 != 0);
    Goto(S5);
S4:
    $InitializeCommonEvent(0, 90015008, 0, 1026500850, 920310, 1026500850, 0, 0);
S5:
    if (1 != 0) {
        $InitializeCommonEvent(0, 90015013);
    }
    $InitializeCommonEvent(0, 90015015, 1026500850);
    $InitializeCommonEvent(0, 90015016, 1026500850);
    if (EventFlag(7604)) {
        $InitializeCommonEvent(0, 90015071, 1026500850);
        $InitializeCommonEvent(0, 90015468, 1026500850, 8270, 8247);
    }
    $InitializeCommonEvent(0, 90015017, 1026500850, 15, 0, 1026500850, 72451, 1026500850);
    $InitializeCommonEvent(0, 90015041, 200, 0, 0, 72486);
    $InitializeCommonEvent(0, 90005201, 1026500850, 30000, 20000, 30, 2, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90015000, 0, 1026500820, 904020540, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 1026500820, 15);
    $InitializeCommonEvent(0, 90015030, 0, 1026500820, 30, 921210, 0);
    $InitializeCommonEvent(0, 90015002, 0, 0, 1026500820, 1026500820, 1020, 921210, 11290, 904020540, 1026500820);
    $InitializeCommonEvent(0, 9005810, 1026500820, 1026500520, 1026501520, 5);
    $InitializeCommonEvent(0, 90015005, 1026501520, 1026502820, 1026500820);
    GotoIf(S6, Signed(0) != 0);
    GotoIf(S6, 0 != 0);
    Goto(S7);
S6:
    $InitializeCommonEvent(0, 90015008, 0, 1026500820, 921210, 1026500820, 0, 0);
S7:
    if (0 != 0) {
        $InitializeCommonEvent(0, 90015013);
    }
    $InitializeCommonEvent(0, 90015015, 1026500820);
    $InitializeCommonEvent(0, 90015016, 1026500820);
    if (EventFlag(7604)) {
        $InitializeCommonEvent(0, 90015071, 1026500820);
        $InitializeCommonEvent(0, 90015468, 1026500820, 8270, 8247);
    }
    $InitializeCommonEvent(0, 90015017, 1026500820, 15, 0, 1026500820, 72461, 1026500820);
    $InitializeCommonEvent(0, 90005201, 1026500820, 30000, 20000, 20, 2, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90015000, 0, 1026500860, 904020540, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 1026500860, 15);
    $InitializeCommonEvent(0, 90015030, 0, 1026500860, 30, 921210, 0);
    $InitializeCommonEvent(0, 90015002, 0, 0, 1026500860, 1026500860, 1020, 921210, 11290, 904020540, 1026500860);
    $InitializeCommonEvent(0, 9005810, 1026500860, 1026500560, 1026501560, 5);
    $InitializeCommonEvent(0, 90015005, 1026501560, 1026502860, 1026500860);
    GotoIf(S8, Signed(0) != 0);
    GotoIf(S8, 0 != 0);
    Goto(S9);
S8:
    $InitializeCommonEvent(0, 90015008, 0, 1026500860, 921210, 1026500860, 0, 0);
S9:
    if (0 != 0) {
        $InitializeCommonEvent(0, 90015013);
    }
    $InitializeCommonEvent(0, 90015015, 1026500860);
    $InitializeCommonEvent(0, 90015016, 1026500860);
    if (EventFlag(7604)) {
        $InitializeCommonEvent(0, 90015071, 1026500860);
        $InitializeCommonEvent(0, 90015468, 1026500860, 8270, 8247);
    }
    $InitializeCommonEvent(0, 90015017, 1026500860, 0, 1026502530, 1026500860, 72466, 1026500860);
    $InitializeCommonEvent(0, 90015041, 60, 0, 0, 72472);
    $InitializeCommonEvent(0, 90005211, 1026500860, 30000, 20000, 1026502530, 5, 1, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90015000, 0, 1026500830, 902100600, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 1026500830, 15);
    $InitializeCommonEvent(0, 90015030, 0, 1026500830, 30, 921510, 0);
    $InitializeCommonEvent(0, 90015002, 0, 0, 1026500830, 1026500830, 1020, 921510, 11290, 902100600, 1026500830);
    $InitializeCommonEvent(0, 9005810, 1026500830, 1026500530, 1026501530, 5);
    $InitializeCommonEvent(0, 90015005, 1026501530, 1026502830, 1026500830);
    GotoIf(S10, Signed(0) != 0);
    GotoIf(S10, 0 != 0);
    Goto(S11);
S10:
    $InitializeCommonEvent(0, 90015008, 0, 1026500830, 921510, 1026500830, 0, 0);
S11:
    if (0 != 0) {
        $InitializeCommonEvent(0, 90015013);
    }
    $InitializeCommonEvent(0, 90015015, 1026500830);
    $InitializeCommonEvent(0, 90015016, 1026500830);
    if (EventFlag(7604)) {
        $InitializeCommonEvent(0, 90015071, 1026500830);
        $InitializeCommonEvent(0, 90015468, 1026500830, 8270, 8247);
    }
    $InitializeCommonEvent(0, 90015017, 1026500830, 15, 0, 1026500830, 72464, 1026500830);
    $InitializeCommonEvent(0, 90015041, 0, 0, 0, 72470);
    $InitializeCommonEvent(0, 90005261, 1026500830, 1026502520, 20, 0, 0);
    $InitializeCommonEvent(0, 90015000, 0, 1026500840, 902100600, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 1026500840, 15);
    $InitializeCommonEvent(0, 90015030, 0, 1026500840, 30, 921510, 0);
    $InitializeCommonEvent(0, 90015002, 0, 0, 1026500840, 1026500840, 1020, 921510, 11290, 902100600, 1026500840);
    $InitializeCommonEvent(0, 9005810, 1026500840, 1026500540, 1026501540, 5);
    $InitializeCommonEvent(0, 90015005, 1026501540, 1026502840, 1026500840);
    GotoIf(S12, Signed(0) != 0);
    GotoIf(S12, 0 != 0);
    Goto(S13);
S12:
    $InitializeCommonEvent(0, 90015008, 0, 1026500840, 921510, 1026500840, 0, 0);
S13:
    if (0 != 0) {
        $InitializeCommonEvent(0, 90015013);
    }
    $InitializeCommonEvent(0, 90015015, 1026500840);
    $InitializeCommonEvent(0, 90015016, 1026500840);
    if (EventFlag(7604)) {
        $InitializeCommonEvent(0, 90015071, 1026500840);
        $InitializeCommonEvent(0, 90015468, 1026500840, 8270, 8247);
    }
    $InitializeCommonEvent(0, 90015017, 1026500840, 15, 0, 1026500840, 72465, 1026500840);
    $InitializeCommonEvent(0, 90015041, 10, 0, 0, 72471);
    $InitializeCommonEvent(0, 90005261, 1026500840, 1026502540, 20, 0, 0);
    $InitializeCommonEvent(0, 90005211, 1026500250, 30001, 20001, 1026502500, 5, 0, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005211, 1026500251, 30001, 20001, 1026502500, 5, 0.5, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1026500300, 30011, 20011, 10, 0.5, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1026500301, 30011, 20011, 10, 0.5, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1026500302, 30011, 20011, 10, 0.5, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1026500303, 30011, 20011, 10, 0.5, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1026500304, 30011, 20011, 10, 0.5, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005200, 1026500200, 30001, 20001, 1026502200, 0, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90015150, 1026500290, 73094);
    $InitializeCommonEvent(0, 90015151, 1026500290, 74054);
    $InitializeCommonEvent(0, 90015152, 1026500290, 74054);
    $InitializeCommonEvent(0, 90015150, 1026500291, 73095);
    $InitializeCommonEvent(0, 90015151, 1026500291, 74055);
    $InitializeCommonEvent(0, 90015152, 1026500291, 74055);
    $InitializeEvent(0, 1026502215);
    if (MissionActive(102)) {
        $InitializeCommonEvent(0, 90085020, 102, 8331, 8332, 8330, 1026500280, 99850, 1026500280, Hero.Wylder);
        $InitializeCommonEvent(0, 90085021, 102, 8331, 1026502280, 1026500280, Hero.Wylder);
        if (1 == 1) {
            $InitializeCommonEvent(0, 90085002, 102, 8332, 8331, 1026500280, 1026505280, 1026500281, 0, 0, 0, 20032);
        }
        if (2 == 1) {
            $InitializeCommonEvent(0, 90085002, 102, 8332, 8331, 1026500280, 1026505280, 1026500281, 1026500282, 0, 0, 20032);
        }
        if (3 == 1) {
            $InitializeCommonEvent(0, 90085002, 102, 8332, 8331, 1026500280, 1026505280, 1026500281, 1026500282, 1026500283, 0, 20032);
        }
        if (4 == 1) {
            $InitializeCommonEvent(0, 90085002, 102, 8332, 8331, 1026500280, 1026505280, 1026500281, 1026500282, 1026500283, 1026500284, 20032);
        }
        $InitializeCommonEvent(0, 90085016, 102, 8332, 8331, 1026500280, 1026505280, 1030, 3);
        $InitializeCommonEvent(0, 90085022, 102, 8332, 1026502281, 1026500280, 501, Hero.Wylder);
        $InitializeCommonEvent(0, 90085023, 102, 8332, 8330, 1026500280, 6851, 1026500280, Hero.Wylder);
        if (1 == 1) {
            $InitializeCommonEvent(0, 90015000, 8331, 1026500281, 912000010, 30, 0, 8332);
            $InitializeCommonEvent(0, 99055500, 1026500281, 15);
        }
        if (1 != 1) {
            $InitializeCommonEvent(0, 90015000, 8331, 1026505280, 912000010, 30, 0, 8332);
            $InitializeCommonEvent(0, 99055500, 1026505280, 15);
        }
        $InitializeCommonEvent(0, 90015030, 0, 1026505280, 30, 920930, 8332);
    }
    if (MissionActive(102)) {
        $InitializeCommonEvent(0, 90085030, 102, 1026500285);
        $InitializeCommonEvent(0, 90085030, 102, 1026500286);
        $InitializeCommonEvent(0, 90085031, 102, 1026501281);
    }
    $InitializeCommonEvent(0, 90085005, 102, Hero.Wylder, 8330, 97120);
});

$Event(1026502200, Default, function(chrEntityId, chrEntityId2, chrEntityId3) {
    EndIf(EventFlag(1026502200));
    ForceAnimationPlayback(chrEntityId2, 30007, true, false, false);
    ForceAnimationPlayback(chrEntityId3, 30007, true, false, false);
    WaitFor(CharacterHasSpEffect(chrEntityId, 10131));
    WaitFixedTimeSeconds(2);
    EnableCharacter(chrEntityId2);
    EnableCharacter(chrEntityId3);
    SetSpEffect(chrEntityId2, 10133);
    SetSpEffect(chrEntityId3, 10133);
    ForceAnimationPlayback(chrEntityId2, 20007, false, false, false);
    ForceAnimationPlayback(chrEntityId3, 20007, false, false, false);
});

$Event(1026502215, Default, function() {
    DisableNetworkSync();
    EndIf(EventFlag(9191));
    CreateAssetfollowingSFX(1026501810, 100, 6164);
    CreateAssetfollowingSFX(1026501811, 100, 807037);
    WaitFor(ActionButtonInArea(4315, 1026501810));
    SetSpEffect(20000, 6999100);
    SetEventFlagID(9191, ON);
    DisplayTextEffectId(2200);
    DeleteAssetfollowingSFX(1026501810, true);
    DeleteAssetfollowingSFX(1026501811, true);
    WaitFixedTimeSeconds(2.5);
    DisplayNetworkconnectedPermanentBuffPopup(2);
});

$Event(1026502220, Default, function() {
    EndIf(EventFlag(1026500800));
    WaitFor(EventFlag(1026500800));
    RecordUserDispLog(11340, 20000, LogObjectType.None, -1);
});
