// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 99055500, 1036500200, 15);
    $InitializeCommonEvent(0, 99055500, 1036500210, 15);
    $InitializeCommonEvent(0, 99055500, 1036500820, 15);
    RegisterBonfire(1036501950, 0, 5);
    $InitializeCommonEvent(0, 90015004, 1036501950, 1036500950);
    $InitializeCommonEvent(0, 90015450, 1036500250, 1036500250);
    $InitializeCommonEvent(0, 90015000, 0, 1036500800, 904500600, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 1036500800, 15);
    $InitializeCommonEvent(0, 90015030, 0, 1036500800, 30, 920310, 0);
    $InitializeCommonEvent(0, 90015002, 0, 0, 1036500800, 1036500800, 1020, 920310, 11290, 904500600, 1036500800);
    $InitializeCommonEvent(0, 9005810, 1036500800, 1036500500, 1036501500, 5);
    $InitializeCommonEvent(0, 90015005, 1036501500, 1036502800, 1036500800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S1);
S0:
    $InitializeCommonEvent(0, 90015008, 0, 1036500800, 920310, 1036500800, 0, 0);
S1:
    if (1 != 0) {
        $InitializeCommonEvent(0, 90015013);
    }
    $InitializeCommonEvent(0, 90015015, 1036500800);
    $InitializeCommonEvent(0, 90015016, 1036500800);
    if (EventFlag(7604)) {
        $InitializeCommonEvent(0, 90015071, 1036500800);
        $InitializeCommonEvent(0, 90015468, 1036500800, 8270, 8247);
    }
    $InitializeCommonEvent(0, 90015017, 1036500800, 15, 0, 1036500800, 72459, 1036500800);
    $InitializeCommonEvent(0, 90015041, 60, 0, 0, 72491);
    $InitializeCommonEvent(0, 90005201, 1036500800, 30005, 20005, 30, 0, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1036500200, 30000, 20000, 30, 2, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005200, 1026500300, 30019, 20019, 1037502520, 1, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005200, 1026500301, 30019, 20019, 1037502520, 1, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005200, 1026500302, 30019, 20019, 1037502520, 1, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1036500210, 30005, 20005, 15, 0, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90015150, 1036500290, 73097);
    $InitializeCommonEvent(0, 90015151, 1036500290, 74057);
    $InitializeCommonEvent(0, 90015152, 1036500290, 74057);
});

$Event(1036502210, Restart, function(chrEntityId) {
    if (!EventFlag(chrEntityId)) {
        WaitFor(HPRatio(chrEntityId) <= 0.7 && CharacterBackreadStatus(chrEntityId));
        ClearCharactersAITarget(chrEntityId);
        RequestCharacterAIReplan(chrEntityId);
        ForceAnimationPlayback(chrEntityId, 0, false, false, false);
        WaitFor(ElapsedFrames(1));
        DisableCharacterAI(chrEntityId);
        DisableCharacterCollision(chrEntityId);
        DisableCharacterHPBarDisplay(chrEntityId);
        ForceAnimationPlayback(chrEntityId, 20015, false, true, false);
        ForceAnimationPlayback(chrEntityId, 30015, true, false, false);
        SetNetworkconnectedEventFlagID(chrEntityId, ON);
        WaitFor(ElapsedSeconds(2));
        DisableCharacter(chrEntityId);
        EndEvent();
    }
L0:
    WaitFor(CharacterBackreadStatus(chrEntityId));
    DisableCharacter(chrEntityId);
    EndEvent();
});
