// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90015000, 0, 46640800, 904670000, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 46640800, 15);
    $InitializeCommonEvent(0, 90015030, 0, 46640800, 30, 467010, 0);
    $InitializeCommonEvent(0, 90015002, 0, 0, 46640800, 46640800, 1020, 467010, 11290, 904670000, 46640800);
    $InitializeCommonEvent(0, 9005810, 46640800, 46640500, 46641500, 5);
    $InitializeCommonEvent(0, 90015005, 46641500, 46642800, 46640800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 1057803469 != 0);
    Goto(S1);
S0:
    $InitializeCommonEvent(0, 90015008, 0, 46640800, 467010, 46640800, 0, 0.55);
S1:
    if (1 != 0) {
        $InitializeCommonEvent(0, 90015013);
    }
    $InitializeCommonEvent(0, 90015015, 46640800);
    $InitializeCommonEvent(0, 90015016, 46640800);
    if (EventFlag(7604)) {
        $InitializeCommonEvent(0, 90015071, 46640800);
        $InitializeCommonEvent(0, 90015468, 46640800, 8270, 8247);
    }
    $InitializeCommonEvent(0, 90015199, 46640800);
    if (IsPlayMode(2)) {
        $InitializeCommonEvent(0, 90015040, 0);
    }
});

$Event(46642200, Default, function(chrEntityId) {
    EndIf(
        !(!EventFlag(7603)
            && (InArea(chrEntityId, 1045392989)
                || InArea(chrEntityId, 1045392988)
                || InArea(chrEntityId, 1044362996)
                || InArea(chrEntityId, 1045382998)
                || InArea(chrEntityId, 1045382997)
                || InArea(chrEntityId, 1045362996)
                || InArea(chrEntityId, 1045362995)
                || InArea(chrEntityId, 1045362994))));
    DisableCharacter(chrEntityId);
    DisableCharacterCollision(chrEntityId);
});
