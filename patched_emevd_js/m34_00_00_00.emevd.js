// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90015310, 34000050, 34000051, 2, 34000200, 34000202, 34000203, 34002405, 34002406, 34002407, 34002410, 34002411, 34002412, 34002415, 34002416, 34002417, 34002420, 34002421, 34002422, 34002400);
    $InitializeCommonEvent(0, 90015301, 34005300, 34000200, 34000201, 34000202, 34000203, 2);
    $InitializeCommonEvent(0, 90015306, 34006500);
    $InitializeCommonEvent(0, 90015303, 34002401);
    $InitializeCommonEvent(0, 90015305, 34002430, 34002431, 34002432, 34002433);
    $InitializeCommonEvent(0, 90015304, 34000050, 34000200, 34000202);
    if (2 >= 2) {
        $InitializeCommonEvent(0, 90015304, 34000051, 34000200, 34000203);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 34005800, 34002800, 30, 904260306, 0, 0);
        $InitializeCommonEvent(0, 99055500, 34005800, 15);
        $InitializeCommonEvent(0, 90015031, 0, 34005800, 34002800, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 34005800, 34002800, 30, 904260306, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 34005800, 34002800, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 34000800, 34005800, 1030, 940000, 11200, 904260306, 34000500);
    $InitializeCommonEvent(0, 90015006, 34001500, 34000500, 34000800, 5);
    $InitializeCommonEvent(0, 90015005, 34001500, 34002800, 34000800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S2);
S0:
    GotoIf(S1, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 34000800, 940000, 34005800, 0, 0);
    Goto(S2);
S1:
    $InitializeCommonEvent(0, 90015008, 0, 34000800, 940000, 34005800, 0, 0);
S2:
    if (IsMapVariation(0)) {
        $InitializeCommonEvent(0, 90015050, 34000800, 8170);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 34000810, 34002810, 30, 903550541, 0, 0);
        $InitializeCommonEvent(0, 99055500, 34000810, 15);
        $InitializeCommonEvent(0, 90015031, 0, 34000810, 34002810, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 34000810, 34002810, 30, 903550541, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 34000810, 34002810, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 34000810, 34000810, 1030, 940000, 11200, 903550541, 34000810);
    $InitializeCommonEvent(0, 90015006, 34001510, 34000510, 34000810, 5);
    $InitializeCommonEvent(0, 90015005, 34001510, 34002810, 34000810);
    GotoIf(S3, Signed(0) != 0);
    GotoIf(S3, 0 != 0);
    Goto(S5);
S3:
    GotoIf(S4, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 34000810, 940000, 34000810, 0, 0);
    Goto(S5);
S4:
    $InitializeCommonEvent(0, 90015008, 0, 34000810, 940000, 34000810, 0, 0);
S5:
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90015050, 34000810, 8170);
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90045040, 1, 34000400);
        $InitializeCommonEvent(0, 90045041, 1, 34000400, 34005200, 34005201);
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90045040, 1, 34000401);
        $InitializeCommonEvent(0, 90045041, 1, 34000401, 34005210, 34005211);
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90045040, 1, 34000402);
        $InitializeCommonEvent(0, 90045041, 1, 34000402, 34005220, 34005221);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 34005820, 34002820, 30, 907100530, 0, 0);
        $InitializeCommonEvent(0, 99055500, 34005820, 15);
        $InitializeCommonEvent(0, 90015031, 0, 34005820, 34002820, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 34005820, 34002820, 30, 907100530, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 34005820, 34002820, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 34000820, 34005820, 1030, 940000, 11200, 907100530, 34000520);
    $InitializeCommonEvent(0, 90015006, 34001520, 34000520, 34000820, 5);
    $InitializeCommonEvent(0, 90015005, 34001520, 34002820, 34000820);
    GotoIf(S6, Signed(0) != 0);
    GotoIf(S6, 0 != 0);
    Goto(S8);
S6:
    GotoIf(S7, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 34000820, 940000, 34005820, 0, 0);
    Goto(S8);
S7:
    $InitializeCommonEvent(0, 90015008, 0, 34000820, 940000, 34005820, 0, 0);
S8:
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015050, 34000820, 8170);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 34005830, 34002830, 30, 903471000, 0, 0);
        $InitializeCommonEvent(0, 99055500, 34005830, 15);
        $InitializeCommonEvent(0, 90015031, 0, 34005830, 34002830, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 34005830, 34002830, 30, 903471000, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 34005830, 34002830, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 34000830, 34005830, 1030, 940000, 11200, 903471000, 34000530);
    $InitializeCommonEvent(0, 90015006, 34001530, 34000530, 34000830, 5);
    $InitializeCommonEvent(0, 90015005, 34001530, 34002830, 34000830);
    GotoIf(S9, Signed(0) != 0);
    GotoIf(S9, 0 != 0);
    Goto(S11);
S9:
    GotoIf(S10, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 34000830, 940000, 34005830, 0, 0);
    Goto(S11);
S10:
    $InitializeCommonEvent(0, 90015008, 0, 34000830, 940000, 34005830, 0, 0);
S11:
    if (IsMapVariation(3)) {
        $InitializeCommonEvent(0, 90015050, 34000830, 8170);
    }
    $InitializeCommonEvent(0, 90035280, 34002491, 34000700, 34000701, 34000702, 8060, 0, 34000800, 34000810, 34000820, 34000830, 0);
    $InitializeCommonEvent(0, 90035280, 34002491, 34000700, 34000701, 34000702, 80010, 0, 34000800, 34000810, 34000820, 34000830, 0);
    $InitializeCommonEvent(0, 90035280, 34002491, 34000700, 34000701, 34000702, 80011, 1, 34000800, 34000810, 34000820, 34000830, 0);
    $InitializeCommonEvent(0, 90035281, 34002491, 34000700, 34000701, 34000702, 80011, 34000800, 34000810, 34000820, 34000830, 0);
    $InitializeCommonEvent(0, 90035282, 34000490, 34002490, 34000700, 34000701, 34000702, 34000703);
    $InitializeCommonEvent(0, 90035283, 34000490, 34002491, 34001690, 34000700, 34000701, 34000702, 34000704, 34000705, 34000706);
    $InitializeCommonEvent(0, 90035284, 34005490, 34005491, 34000700, 34000702, 34000705, 34000706);
    $InitializeCommonEvent(0, 90035285, 34000490, 34000700, 34000701, 34000702, 34000705, 34000706);
    $InitializeCommonEvent(0, 90035286, 34000490, 34002491, 34000700, 34000701, 34000702, 34000705, 34000706);
    $InitializeCommonEvent(0, 90035288, 34002491, 34000700, 34000702, 34000705, 34000706);
    $InitializeCommonEvent(0, 90015000, 34000704, 34000490, 907640001, 50, 0, 34000706);
    $InitializeCommonEvent(0, 99055500, 34000490, 15);
    $InitializeCommonEvent(0, 90015025, 8081, 34000704, 34000705, 34000490, 1020, 0, -1, -1, 34000490, 0);
    $InitializeCommonEvent(0, 90005526, 34000500, 34001200);
    $InitializeEvent(0, 34002600);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 0, 34000800);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 1, 34000810);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 2, 34000820);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 3, 34000830);
});

$Event(34002600, Restart, function() {
    if (!IsMapVariation(2)) {
        DeleteMapSFX(34002600, false);
        DeleteMapSFX(34002601, false);
        DeleteMapSFX(34002602, false);
        DeleteMapSFX(34002603, false);
        DeleteMapSFX(34002604, false);
        DeleteMapSFX(34002605, false);
        DeleteMapSFX(34002606, false);
        DeleteMapSFX(34002607, false);
        DeleteMapSFX(34002608, false);
        DeleteMapSFX(34002609, false);
        DeleteMapSFX(34002610, false);
        DeleteMapSFX(34002611, false);
        EndEvent();
    }
L0:
    EndEvent();
});

$Event(34002800, Restart, function(chrEntityId) {
    EndIf(EventFlag(chrEntityId));
    WaitFor(CharacterHPValue(chrEntityId) <= 0);
    WaitFixedTimeSeconds(4);
    PlaySE(chrEntityId, SoundType.SFX, 888880000);
    WaitFor(CharacterDead(chrEntityId));
    HandleMinibossDefeat(chrEntityId);
    SetEventFlagID(chrEntityId, ON);
});

$Event(34002801, Restart, function(chrEntityId, chrEntityId2) {
    EndIf(EventFlag(chrEntityId));
    WaitFor(CharacterDead(chrEntityId) && CharacterDead(chrEntityId2));
    WaitFixedTimeSeconds(3);
    HandleMinibossDefeat(chrEntityId);
    SetEventFlagID(chrEntityId, ON);
});

$Event(34002802, Restart, function(chrEntityId) {
    EndIf(EventFlag(chrEntityId));
    WaitFor(CharacterHPValue(chrEntityId) <= 0);
    WaitFixedTimeSeconds(4);
    PlaySE(chrEntityId, SoundType.SFX, 888880000);
});

$Event(34002803, Restart, function(chrEntityId) {
    EndIf(EventFlag(chrEntityId));
    WaitFor(CharacterHPValue(chrEntityId) <= 0);
    WaitFixedTimeSeconds(4);
    PlaySE(chrEntityId, SoundType.SFX, 888880000);
});
