import sympy as sp
from collections import OrderedDict, Sequence

from lbmpy.methods.abstractlbmethod import AbstractLbMethod, LbmCollisionRule, RelaxationInfo
from lbmpy.methods.conservedquantitycomputation import AbstractConservedQuantityComputation
from lbmpy.moments import MOMENT_SYMBOLS, momentMatrix, isShearMoment
from pystencils.sympyextensions import replaceAdditive


class MomentBasedLbMethod(AbstractLbMethod):
    def __init__(self, stencil, momentToRelaxationInfoDict, conservedQuantityComputation=None, forceModel=None):
        """
        Moment based LBM is a class to represent the single (SRT), two (TRT) and multi relaxation time (MRT) methods.
        These methods work by transforming the pdfs into moment space using a linear transformation. In the moment
        space each component (moment) is relaxed to an equilibrium moment by a certain relaxation rate. These
        equilibrium moments can e.g. be determined by taking the equilibrium moments of the continuous Maxwellian.

        :param stencil: see :func:`lbmpy.stencils.getStencil`
        :param momentToRelaxationInfoDict: a dictionary mapping moments in either tuple or polynomial formulation
                                           to a RelaxationInfo, which consists of the corresponding equilibrium moment
                                           and a relaxation rate
        :param conservedQuantityComputation: instance of :class:`lbmpy.methods.AbstractConservedQuantityComputation`.
                                             This determines how conserved quantities are computed, and defines
                                             the symbols used in the equilibrium moments like e.g. density and velocity
        :param forceModel: force model instance, or None if no forcing terms are required
        """
        assert isinstance(conservedQuantityComputation, AbstractConservedQuantityComputation)
        super(MomentBasedLbMethod, self).__init__(stencil)

        self._forceModel = forceModel
        self._momentToRelaxationInfoDict = OrderedDict(momentToRelaxationInfoDict.items())
        self._conservedQuantityComputation = conservedQuantityComputation
        self._weights = None

        equilibriumMoments = []
        for moment, relaxInfo in momentToRelaxationInfoDict.items():
            equilibriumMoments.append(relaxInfo.equilibriumValue)
        symbolsInEquilibriumMoments = sp.Matrix(equilibriumMoments).atoms(sp.Symbol)
        conservedQuantities = set()
        for v in self._conservedQuantityComputation.definedSymbols().values():
            if isinstance(v, Sequence):
                conservedQuantities.update(v)
            else:
                conservedQuantities.add(v)
        undefinedEquilibriumSymbols = symbolsInEquilibriumMoments - conservedQuantities

        assert len(undefinedEquilibriumSymbols) == 0, "Undefined symbol(s) in equilibrium moment: %s" % \
                                                      (undefinedEquilibriumSymbols,)

    @property
    def momentToRelaxationInfoDict(self):
        return self._momentToRelaxationInfoDict

    @property
    def conservedQuantityComputation(self):
        return self._conservedQuantityComputation

    @property
    def moments(self):
        return tuple(self._momentToRelaxationInfoDict.keys())

    @property
    def momentEquilibriumValues(self):
        return tuple([e.equilibriumValue for e in self._momentToRelaxationInfoDict.values()])

    @property
    def relaxationRates(self):
        return tuple([e.relaxationRate for e in self._momentToRelaxationInfoDict.values()])

    @property
    def zerothOrderEquilibriumMomentSymbol(self, ):
        return self._conservedQuantityComputation.zerothOrderMomentSymbol

    @property
    def firstOrderEquilibriumMomentSymbols(self, ):
        return self._conservedQuantityComputation.firstOrderMomentSymbols

    @property
    def weights(self):
        if self._weights is None:
            self._weights = self._computeWeights()
        return self._weights

    def getShearRelaxationRate(self):
        """
        Assumes that all shear moments are relaxed with same rate - returns this rate
        Shear moments in 3D are: x*y, x*z and y*z - in 2D its only x*y
        The shear relaxation rate determines the viscosity in hydrodynamic LBM schemes
        """
        relaxationRates = set()
        for moment, relaxInfo in self._momentToRelaxationInfoDict.items():
            if isShearMoment(moment):
                relaxationRates.add(relaxInfo.relaxationRate)
        if len(relaxationRates) == 1:
            return relaxationRates.pop()
        else:
            if len(relaxationRates) > 1:
                raise ValueError("Shear moments are relaxed with different relaxation times: %s" % (relaxationRates,))
            else:
                raise NotImplementedError("Shear moments seem to be not relaxed separately - "
                                          "Can not determine their relaxation rate automatically")

    def getEquilibrium(self, conservedQuantityEquations=None):
        D = sp.eye(len(self.relaxationRates))
        return self._getCollisionRuleWithRelaxationMatrix(D, conservedQuantityEquations=conservedQuantityEquations)

    def getCollisionRule(self, conservedQuantityEquations=None):
        D = sp.diag(*self.relaxationRates)
        relaxationRateSubExpressions, D = self._generateRelaxationMatrix(D)
        eqColl = self._getCollisionRuleWithRelaxationMatrix(D, relaxationRateSubExpressions, conservedQuantityEquations)
        if self._forceModel is not None:
            forceModelTerms = self._forceModel(self)
            newEqs = [sp.Eq(eq.lhs, eq.rhs + fmt) for eq, fmt in zip(eqColl.mainEquations, forceModelTerms)]
            eqColl = eqColl.copy(newEqs)
        return eqColl

    def setFirstMomentRelaxationRate(self, relaxationRate):
        for e in MOMENT_SYMBOLS[:self.dim]:
            assert e in self._momentToRelaxationInfoDict, "First moments are not relaxed separately by this method"
        for e in MOMENT_SYMBOLS[:self.dim]:
            prevEntry = self._momentToRelaxationInfoDict[e]
            newEntry = RelaxationInfo(prevEntry[0], relaxationRate)
            self._momentToRelaxationInfoDict[e] = newEntry

    def _repr_html_(self):
        table = """
        <table style="border:none; width: 100%">
            <tr {nb}>
                <th {nb} >Moment</th>
                <th {nb} >Eq. Value </th>
                <th {nb} >Relaxation Time</th>
            </tr>
            {content}
        </table>
        """
        content = ""
        for moment, (eqValue, rr) in self._momentToRelaxationInfoDict.items():
            vals = {
                'rr': sp.latex(rr),
                'moment': sp.latex(moment),
                'eqValue': sp.latex(eqValue),
                'nb': 'style="border:none"',
            }
            content += """<tr {nb}>
                            <td {nb}>${moment}$</td>
                            <td {nb}>${eqValue}$</td>
                            <td {nb}>${rr}$</td>
                         </tr>\n""".format(**vals)
        return table.format(content=content, nb='style="border:none"')

    def _computeWeights(self):
        replacements = self._conservedQuantityComputation.defaultValues
        eqColl = self.getEquilibrium().copyWithSubstitutionsApplied(replacements).insertSubexpressions()
        newMainEqs = [sp.Eq(e.lhs,
                            replaceAdditive(e.rhs, 1, sum(self.preCollisionPdfSymbols), requiredMatchReplacement=1.0))
                      for e in eqColl.mainEquations]
        eqColl = eqColl.copy(newMainEqs)

        weights = []
        for eq in eqColl.mainEquations:
            value = eq.rhs.expand()
            assert len(value.atoms(sp.Symbol)) == 0, "Failed to compute weights"
            weights.append(value)
        return weights

    def _getCollisionRuleWithRelaxationMatrix(self, D, additionalSubexpressions=(), conservedQuantityEquations=None):
        f = sp.Matrix(self.preCollisionPdfSymbols)
        M = momentMatrix(self.moments, self.stencil)
        m_eq = sp.Matrix(self.momentEquilibriumValues)

        collisionRule = f + M.inv() * D * (m_eq - M * f)
        collisionEqs = [sp.Eq(lhs, rhs) for lhs, rhs in zip(self.postCollisionPdfSymbols, collisionRule)]

        if conservedQuantityEquations is None:
            conservedQuantityEquations = self._conservedQuantityComputation.equilibriumInputEquationsFromPdfs(f)

        simplificationHints = conservedQuantityEquations.simplificationHints
        simplificationHints.update(self._conservedQuantityComputation.definedSymbols())
        simplificationHints['relaxationRates'] = D.atoms(sp.Symbol)

        allSubexpressions = list(additionalSubexpressions) + conservedQuantityEquations.allEquations
        return LbmCollisionRule(self, collisionEqs, allSubexpressions,
                                simplificationHints)

    @staticmethod
    def _generateRelaxationMatrix(relaxationMatrix):
        """
        For SRT and TRT the equations can be easier simplified if the relaxation times are symbols, not numbers.
        This function replaces the numbers in the relaxation matrix with symbols in this case, and returns also
         the subexpressions, that assign the number to the newly introduced symbol
        """
        rr = [relaxationMatrix[i, i] for i in range(relaxationMatrix.rows)]
        uniqueRelaxationRates = set(rr)
        if len(uniqueRelaxationRates) <= 2:
            # special handling for SRT and TRT
            subexpressions = {}
            for rt in uniqueRelaxationRates:
                rt = sp.sympify(rt)
                if not isinstance(rt, sp.Symbol):
                    rtSymbol = sp.Symbol("rt_%d" % (len(subexpressions),))
                    subexpressions[rt] = rtSymbol

            newRR = [subexpressions[sp.sympify(e)] if sp.sympify(e) in subexpressions else e
                     for e in rr]
            substitutions = [sp.Eq(e[1], e[0]) for e in subexpressions.items()]
            return substitutions, sp.diag(*newRR)
        else:
            return [], relaxationMatrix




