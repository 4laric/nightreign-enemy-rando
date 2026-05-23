// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90015000, 0, 46670800, 904810600, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 46670800, 15);
    $InitializeCommonEvent(0, 90015030, 0, 46670800, 30, 920610, 0);
    $InitializeCommonEvent(0, 90015002, 0, 0, 46670800, 46670800, 1020, 920610, 11290, 904810600, 46670800);
    $InitializeCommonEvent(0, 9005810, 46670800, 46670500, 46671500, 5);
    $InitializeCommonEvent(0, 90015005, 46671500, 46672800, 46670800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S1);
S0:
    $InitializeCommonEvent(0, 90015008, 0, 46670800, 920610, 46670800, 0, 0);
S1:
    if (1 != 0) {
        $InitializeCommonEvent(0, 90015013);
    }
    $InitializeCommonEvent(0, 90015015, 46670800);
    $InitializeCommonEvent(0, 90015016, 46670800);
    if (EventFlag(7604)) {
        $InitializeCommonEvent(0, 90015071, 46670800);
        $InitializeCommonEvent(0, 90015468, 46670800, 8270, 8247);
    }
    $InitializeCommonEvent(0, 90015199, 46670800);
    if (IsPlayMode(2)) {
        $InitializeCommonEvent(0, 90015040, 0);
    }
});

$Event(46672200, Default, function(chrEntityId) {
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
